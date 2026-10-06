# Excepciones para conversiones decimales y función de renderizado de Django.
import re
import time
from decimal import Decimal, InvalidOperation
from io import BytesIO
from math import ceil

from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

# Modelo de tarifas y funciones de cálculo compartidas por la vista.
from .forms import FreightRateEntryForm
from .models import FreightRate, Route
from .services import DESTINATIONS, container_count, convert_currency, format_amount


class CintacLoginView(auth_views.LoginView):
    max_failed_attempts = 3
    lock_seconds = 10
    failed_attempts_session_key = "cintac_login_failed_attempts"
    locked_until_session_key = "cintac_login_locked_until"

    def _remaining_lock_seconds(self):
        locked_until = self.request.session.get(self.locked_until_session_key)
        if locked_until is None:
            return 0

        remaining = ceil(locked_until - time.time())
        if remaining <= 0:
            self.request.session.pop(self.locked_until_session_key, None)
            self.request.session.pop(self.failed_attempts_session_key, None)
            return 0
        return remaining

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["login_wait_seconds"] = self._remaining_lock_seconds()
        return context

    def post(self, request, *args, **kwargs):
        remaining = self._remaining_lock_seconds()
        if remaining:
            form = self.get_form()
            form.add_error(None, "Se alcanzó el límite de intentos.")
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        invalid_login_errors = form.errors.as_data().get("__all__", [])
        if any(error.code == "invalid_login" for error in invalid_login_errors):
            attempts = self.request.session.get(self.failed_attempts_session_key, 0) + 1
            if attempts >= self.max_failed_attempts:
                self.request.session.pop(self.failed_attempts_session_key, None)
                self.request.session[self.locked_until_session_key] = time.time() + self.lock_seconds
                form.add_error(None, "Demasiados intentos fallidos. Espera 10 segundos para volver a intentarlo.")
            else:
                self.request.session[self.failed_attempts_session_key] = attempts
        return super().form_invalid(form)

    def form_valid(self, form):
        self.request.session.pop(self.failed_attempts_session_key, None)
        self.request.session.pop(self.locked_until_session_key, None)
        return super().form_valid(form)


def _convert_optional(amount, source, target, exchange_rate):
    # Conserva los valores opcionales sin convertir cuando no hay monto o destino.
    if amount is None:
        return None
    if not target:
        return amount
    return convert_currency(amount, source, target, exchange_rate)


def _quote_excel_response(result, form):
    rate = result["rate"]
    container_size = result["container_size"]
    unit_min = rate.freight_20 if container_size == "20" else rate.freight_40
    unit_max = rate.freight_20_max if container_size == "20" else rate.freight_40_max
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Cotización"
    rows = [
        ["CINTAC | Cotización marítima"],
        ["Operación", dict(FreightRate.OPERATION_CHOICES)[rate.operation]],
        ["Origen", rate.route.origin_port, rate.route.country],
        ["Destino", result["destination"]],
        ["Tipo de ruta", result["route_type"] or "Sin especificar"],
        ["Fuente", result["source"] or "Sin especificar"],
        ["Tamaño de contenedor", f"{container_size} pies"],
        ["Peso informado", form["weight"], form["weight_unit"]],
        ["Peso convertido", result["tonnes"], "TN"],
        ["Cantidad de contenedores", result["quantity"]],
        ["Flete unitario mínimo", format_amount(unit_min), rate.currency],
        [
            "Flete unitario máximo",
            format_amount(unit_max) if unit_max is not None else "Sin máximo",
            rate.currency,
        ],
        ["Flete total mínimo", result["amount"], result["currency"]],
        [
            "Flete total máximo",
            result["amount_max"] or "Sin máximo",
            result["currency"],
        ],
        ["Tránsito base mínimo", result["base_days"], "días"],
        [
            "Tránsito base máximo",
            result["base_days_max"] if result["base_days_max"] is not None else "Sin máximo",
            "días",
        ],
        ["Margen agregado", result["margin_days"], "días"],
        ["Tránsito estimado mínimo", result["total_days"], "días"],
        [
            "Tránsito estimado máximo",
            result["total_days_max"] if result["total_days_max"] is not None else "Sin máximo",
            "días",
        ],
    ]
    if result["converted"]:
        rows.append(["Tipo de cambio aplicado", form["exchange_rate"], "CLP por USD"])

    for row in rows:
        sheet.append(row)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"

    sheet.append([])
    sheet.append(["Comparación de alternativas"])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="303030")
    sheet.append(["Embarcador", "Flete total", "Moneda", "Tránsito estimado"])
    for item in result["comparisons"]:
        sheet.append([item["carrier"], item["amount"], item["currency"], f'{item["days"]} días'])
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"

    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF", size=14)
        cell.fill = PatternFill("solid", fgColor="E96F00")
    for cell in sheet[sheet.max_row - len(result["comparisons"])]:
        cell.font = Font(bold=True)
    sheet.column_dimensions["A"].width = 32
    sheet.column_dimensions["B"].width = 28
    sheet.column_dimensions["C"].width = 20
    sheet.column_dimensions["D"].width = 24
    sheet.freeze_panes = "A2"

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="cotizacion_cintac.xlsx"'
    return response


@never_cache
@login_required
def quote(request):
    # Carga tarifas con su ruta; el formulario limita la selección por operación.
    rates = list(FreightRate.objects.select_related("route"))
    requested_operation = request.POST.get("operation", request.GET.get("operation", "import"))
    if requested_operation not in dict(FreightRate.OPERATION_CHOICES):
        requested_operation = "import"
    operation_rates = [rate for rate in rates if rate.operation == requested_operation]
    selected_rate_id = operation_rates[0].pk if operation_rates else ""
    # Valores iniciales del formulario que también se usan para solicitudes GET.
    form = {
        "operation": requested_operation,
        "transport": "sea",
        "rate_id": selected_rate_id,
        "destination": DESTINATIONS[0],
        "weight": "",
        "weight_unit": "kg",
        "container_size": "20",
        "margin_days": "0",
        "target_currency": "",
        "exchange_rate": "",
    }
    result = None
    error = ""

    if request.method == "POST":
        # Mantiene solo los campos reconocidos por el formulario.
        for field in form:
            if field in request.POST:
                form[field] = request.POST[field]
        try:
            if form["operation"] not in dict(FreightRate.OPERATION_CHOICES):
                raise ValueError("Selecciona una operación válida.")
            if form["transport"] != "sea":
                raise ValueError("No hay tarifas aéreas cargadas. Agrega datos validados antes de cotizar por avión.")
            if not operation_rates:
                operation_display = dict(FreightRate.OPERATION_CHOICES)[form["operation"]].lower()
                raise ValueError(f"No hay tarifas de {operation_display} cargadas en los antecedentes.")
            if form["operation"] == "import" and form["destination"] not in DESTINATIONS:
                raise ValueError("Selecciona uno de los destinos predefinidos.")

            rate = FreightRate.objects.select_related("route").get(
                pk=form["rate_id"],
                operation=form["operation"],
            )
            destination = rate.destination_port or form["destination"]
            if form["operation"] == "export" and not destination:
                raise ValueError("La tarifa de exportación debe tener un puerto de destino.")
            if rate.destination_port and form["destination"] != rate.destination_port:
                form["destination"] = rate.destination_port

            # Convierte el peso y calcula contenedores con la capacidad configurada.
            tonnes, quantity = container_count(form["weight"], form["weight_unit"])
            # Solo se admiten los tamaños para los que el modelo mantiene tarifas.
            if form["container_size"] not in {"20", "40"}:
                raise ValueError("Selecciona un contenedor de 20 o 40 pies.")
            # Valida el margen de tránsito antes de sumarlo a los días base.
            try:
                margin_days = int(form["margin_days"])
            except (TypeError, ValueError) as exception:
                raise ValueError("Ingresa un margen de días entero y no negativo.") from exception
            if margin_days < 0:
                raise ValueError("El margen de días no puede ser negativo.")

            # Toma el precio mínimo y máximo según el tamaño seleccionado.
            if form["container_size"] == "20":
                unit_min = rate.freight_20
                unit_max = rate.freight_20_max
            else:
                unit_min = rate.freight_40
                unit_max = rate.freight_40_max

            # Multiplica el precio por la cantidad calculada, conservando el rango.
            amount_min = unit_min * quantity
            amount_max = unit_max * quantity if unit_max is not None else None
            currency = rate.currency
            target_currency = form["target_currency"]
            converted = bool(target_currency and target_currency != currency)

            # Convierte ambos extremos del precio cuando se solicitó otra moneda.
            amount_min = _convert_optional(amount_min, currency, target_currency, form["exchange_rate"])
            amount_max = _convert_optional(amount_max, currency, target_currency, form["exchange_rate"])
            result_currency = target_currency or currency

            # Calcula el tiempo total; el máximo solo existe si la tarifa tiene rango.
            base_days_max = rate.transit_days_max
            total_days_max = base_days_max + margin_days if base_days_max is not None else None

            # Prepara los datos formateados que consume el panel de resultado.
            result = {
                "rate": rate,
                "destination": destination,
                "tonnes": format_amount(tonnes),
                "quantity": quantity,
                "container_size": form["container_size"],
                "base_days": rate.transit_days,
                "base_days_max": base_days_max,
                "margin_days": margin_days,
                "total_days": rate.transit_days + margin_days,
                "total_days_max": total_days_max,
                "amount": format_amount(amount_min),
                "amount_max": format_amount(amount_max) if amount_max is not None else "",
                "currency": result_currency,
                "converted": converted,
                "route_type": rate.route_type,
                "source": rate.source,
                "comparisons": [],
                "comparison_unavailable": "",
            }

            # Busca tarifas del mismo origen y destino para comparar alternativas.
            alternatives = list(
                FreightRate.objects.filter(
                    operation=rate.operation,
                    route=rate.route,
                    destination_port=rate.destination_port,
                ).select_related("route")
            )
            currencies = {alternative.currency for alternative in alternatives}
            # Informa por qué no es válido comparar si faltan alternativas o moneda común.
            if len(alternatives) < 2:
                result["comparison_unavailable"] = "No hay otros embarcadores cargados para esta misma ruta."
            elif len(currencies) != 1:
                result["comparison_unavailable"] = "Confirma una misma moneda para todas las tarifas antes de compararlas."
            else:
                # Calcula el total por alternativa usando el tamaño y peso ya validados.
                for alternative in alternatives:
                    alt_unit = alternative.freight_20 if form["container_size"] == "20" else alternative.freight_40
                    alternative_amount = alt_unit * quantity
                    if target_currency:
                        alternative_amount = convert_currency(
                            alternative_amount,
                            alternative.currency,
                            target_currency,
                            form["exchange_rate"],
                        )
                    result["comparisons"].append(
                        {
                            "carrier": alternative.carrier or alternative.source or "Alternativa sin identificar",
                            "amount": format_amount(alternative_amount),
                            "currency": target_currency or alternative.currency,
                            "days": alternative.transit_days + margin_days,
                        }
                    )
                # Ordena de menor a mayor precio, deshaciendo antes el formato local.
                result["comparisons"].sort(
                    key=lambda item: Decimal(item["amount"].replace(".", "").replace(",", "."))
                )
        except FreightRate.DoesNotExist:
            # La tarifa enviada ya no existe o no corresponde a un registro válido.
            error = (
                f"No hay tarifas de {dict(FreightRate.OPERATION_CHOICES)[form['operation']].lower()} "
                "cargadas en los antecedentes."
                if not operation_rates
                else "Selecciona una tarifa de origen válida para la operación elegida."
            )
        except ValueError as exception:
            # Presenta al usuario los errores de validación con su mensaje específico.
            error = str(exception)
        except (InvalidOperation, TypeError):
            # Cubre entradas numéricas inválidas sin ocultar el error al usuario.
            error = "Revisa los datos ingresados y confirma el tipo de cambio cuando solicites conversión."

    if request.method == "POST" and request.POST.get("export_excel") and result is not None:
        return _quote_excel_response(result, form)

    # Convierte el identificador para que la plantilla pueda marcar la tarifa elegida.
    try:
        selected_rate_id = int(form["rate_id"])
    except (TypeError, ValueError):
        selected_rate_id = ""

    # Renderiza formulario, opciones, resultado y mensajes de error de la solicitud.
    return render(
        request,
        "cotizador/index.html",
        {
            "rates": rates,
            "destinations": list(
                dict.fromkeys(
                    (*DESTINATIONS, *(rate.destination_port for rate in rates if rate.destination_port))
                )
            ),
            "form": form,
            "selected_rate_id": selected_rate_id,
            "result": result,
            "error": error,
            "no_rates_message": (
                f"No hay tarifas de {dict(FreightRate.OPERATION_CHOICES)[requested_operation][1].lower()} "
                "cargadas en los antecedentes."
            ) if not operation_rates and request.method == "GET" else "",
        },
    )


@never_cache
@login_required
def rates(request):
    search = request.GET.get("q", "").strip()
    operation = request.GET.get("operation", "all")
    if operation not in {"all", *dict(FreightRate.OPERATION_CHOICES)}:
        operation = "all"
    queryset = FreightRate.objects.select_related("route")
    if operation != "all":
        queryset = queryset.filter(operation=operation)
    if search:
        queryset = queryset.filter(
            Q(route__country__icontains=search)
            | Q(route__origin_port__icontains=search)
            | Q(destination_port__icontains=search)
            | Q(carrier__icontains=search)
            | Q(route_type__icontains=search)
            | Q(source__icontains=search)
        )

    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    rate_rows = [
        {
            "rate": rate,
            "freight_20": format_amount(rate.freight_20),
            "freight_20_max": format_amount(rate.freight_20_max) if rate.freight_20_max is not None else "",
            "freight_40": format_amount(rate.freight_40),
            "freight_40_max": format_amount(rate.freight_40_max) if rate.freight_40_max is not None else "",
            "source_label": _rate_source_label(rate.source),
        }
        for rate in page.object_list
    ]
    return render(
        request,
        "cotizador/rates.html",
        {
            "page_obj": page,
            "rate_rows": rate_rows,
            "search": search,
            "total_rates": page.paginator.count,
            "operation": operation,
            "can_add_rates": request.user.has_perm("cotizador.add_freightrate"),
            "can_edit_rates": request.user.has_perm("cotizador.change_freightrate"),
            "can_delete_rates": request.user.has_perm("cotizador.delete_freightrate"),
        },
    )


def _rate_source_label(source):
    if not source:
        return "Antecedente sin referencia de archivo"
    excel_row = re.search(r"Importaciones!A(\d+):H\d+", source)
    if excel_row:
        return f"Excel de tarifas · Importaciones, fila {excel_row.group(1)}"
    return source


@never_cache
@login_required
@permission_required("cotizador.add_freightrate", raise_exception=True)
def rate_create(request):
    if request.method == "POST":
        form = FreightRateEntryForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    rate = form.save(commit=False)
                    rate.route = _route_from_choice(form.cleaned_data["origin_route"])
                    rate.save()
            except IntegrityError:
                form.add_error(
                    None,
                    "Ya existe una tarifa para esta ruta, operación, destino y embarcador.",
                )
            else:
                messages.success(request, f"Tarifa de {rate.get_operation_display().lower()} guardada correctamente.")
                return redirect("rates")
    else:
        form = FreightRateEntryForm()
    return render(request, "cotizador/rate_form.html", {"form": form, "editing": False})


@never_cache
@login_required
@permission_required("cotizador.change_freightrate", raise_exception=True)
def rate_edit(request, rate_id):
    rate = get_object_or_404(FreightRate.objects.select_related("route"), pk=rate_id)
    if request.method == "POST":
        form = FreightRateEntryForm(request.POST, instance=rate)
        if form.is_valid():
            try:
                with transaction.atomic():
                    updated_rate = form.save(commit=False)
                    updated_rate.route = _route_from_choice(form.cleaned_data["origin_route"])
                    updated_rate.save()
            except IntegrityError:
                form.add_error(
                    None,
                    "Ya existe una tarifa para esta ruta, operación, destino y embarcador.",
                )
            else:
                messages.success(
                    request,
                    f"Tarifa de {updated_rate.get_operation_display().lower()} actualizada correctamente.",
                )
                return redirect("rates")
    else:
        form = FreightRateEntryForm(instance=rate)
    return render(
        request,
        "cotizador/rate_form.html",
        {"form": form, "editing": True, "rate": rate},
    )


def _route_from_choice(value):
    route_type, _, route_value = value.partition(":")
    if route_type == "route":
        return get_object_or_404(Route, pk=route_value)
    country, separator, origin_port = route_value.partition("|")
    if route_type != "catalog" or not separator:
        raise ValueError("Selecciona una ruta de origen válida.")
    route, _ = Route.objects.get_or_create(country=country, origin_port=origin_port)
    return route


@never_cache
@login_required
@permission_required("cotizador.delete_freightrate", raise_exception=True)
def rate_delete(request, rate_id):
    rate = get_object_or_404(
        FreightRate.objects.select_related("route"),
        pk=rate_id,
    )
    if request.method == "POST":
        description = str(rate)
        operation = rate.get_operation_display().lower()
        rate.delete()
        messages.success(request, f"Tarifa de {operation} eliminada: {description}.")
        return redirect("rates")
    return render(request, "cotizador/rate_confirm_delete.html", {"rate": rate})
