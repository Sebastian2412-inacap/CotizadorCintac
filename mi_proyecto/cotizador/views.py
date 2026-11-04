# Excepciones para conversiones decimales y función de renderizado de Django.
import re
import time
from decimal import Decimal, InvalidOperation
from io import BytesIO
from math import ceil

from django.contrib.auth import get_user_model, views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db import IntegrityError, transaction
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

# Modelo de tarifas y funciones de cálculo compartidas por la vista.
from .forms import (
    FreightRateEntryForm,
    ManagedUserCreateForm,
    ManagedUserUpdateForm,
    UserProfileForm,
)
from .models import FreightRate, QuoteHistory, Route, UserProfile
from .permissions import (
    TARIFF_ADMIN_GROUP,
    can_view_all_quotes,
    is_tariff_admin,
    is_user_manager,
    tariff_admin_required,
    user_manager_required,
)
from .services import (
    DESTINATIONS,
    container_count,
    convert_currency,
    fetch_latest_usd_clp_rate,
    format_amount,
)


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
        ["Operación", "Importación"],
        ["Origen", rate.route.origin_port, rate.route.country],
        ["Destino", result["destination"]],
        ["Tipo de ruta", result["route_type"] or "Sin especificar"],
        ["Fuente", result["source"] or "Sin especificar"],
        ["Tamaño recomendado", f"{container_size} pies"],
        [
            "Recomendación económica",
            f'{result["recommendation"]["quantity"]} contenedor(es) de {result["recommendation"]["size"]} pies',
            f'{result["recommendation"]["currency"]} {result["recommendation"]["amount"]}',
        ],
        ["Peso informado", form["weight"], form["weight_unit"]],
        ["Peso convertido", result["tonnes"], "TN"],
        ["Cantidad de contenedores", result["quantity"]],
        ["Flete unitario mínimo", format_amount(unit_min, rate.currency), rate.currency],
        [
            "Flete unitario máximo",
            format_amount(unit_max, rate.currency) if unit_max is not None else "Sin máximo",
            rate.currency,
        ],
        ["Flete total mínimo", result["amount"], result["currency"]],
        [
            "Flete total máximo",
            result["amount_max"] or "Sin máximo",
            result["currency"],
        ],
        ["Monto base mínimo", result["source_amount"], result["source_currency"]],
        [
            "Monto base máximo",
            result["source_amount_max"] or "Sin máximo",
            result["source_currency"],
        ],
        ["Tarifa registrada mínimo", result["rate_amount"], result["rate_currency"]],
        [
            "Tarifa registrada máximo",
            result["rate_amount_max"] or "Sin máximo",
            result["rate_currency"],
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
        rows.append(["Fecha del tipo de cambio", result["exchange_rate_date"]])

    for row in rows:
        sheet.append(row)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"

    sheet.append([])
    comparison_start = sheet.max_row + 1
    sheet.append(["Comparativa de presupuesto por tamaño de contenedor"])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="303030")
    sheet.append(
        [
            "Contenedor",
            "Cantidad",
            "Capacidad máxima por unidad",
            "Tarifa base total mínimo",
            "Tarifa base total máximo",
            "Moneda base",
            "Total cotización mínimo",
            "Total cotización máximo",
            "Moneda cotización",
        ]
    )
    container_header_row = sheet.max_row
    for option in result["container_options"]:
        sheet.append(
            [
                f'{option["size"]} pies',
                option["quantity"],
                f'{option["capacity"]} TN',
                format_amount(option["source_amount"], option["source_currency"]),
                (
                    format_amount(option["source_amount_max"], option["source_currency"])
                    if option["source_amount_max"] is not None
                    else "Sin máximo"
                ),
                option["source_currency"],
                option["amount"],
                option["amount_max"] or "Sin máximo",
                option["currency"],
            ]
        )
    for row in sheet.iter_rows(min_row=comparison_start + 1, max_row=sheet.max_row):
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    for cell in sheet[container_header_row]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="FFF1DF")

    sheet.append([])
    alternative_start = sheet.max_row + 1
    sheet.append(["Comparación de alternativas de embarcador"])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="303030")
    sheet.append(
        [
            "Embarcador",
            "Tarifa unitaria mínima",
            "Tarifa unitaria máxima",
            "Moneda tarifa",
            "Cantidad de contenedores",
            "Total estimado mínimo",
            "Total estimado máximo",
            "Moneda cotización",
            "Tránsito estimado mínimo",
            "Tránsito estimado máximo",
            "Tipo de ruta",
            "Fuente",
        ]
    )
    for item in result["comparisons"]:
        sheet.append(
            [
                item["carrier"],
                item["unit_amount"],
                item["unit_amount_max"] or "Sin máximo",
                item["rate_currency"],
                item["quantity"],
                item["amount"],
                item["amount_max"] or "Sin máximo",
                item["currency"],
                item["days"],
                item["days_max"] if item["days_max"] is not None else "Sin máximo",
                item["route_type"] or "Sin especificar",
                item["source"] or "Sin especificar",
            ]
        )
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"

    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF", size=14)
        cell.fill = PatternFill("solid", fgColor="E96F00")
    for cell in sheet[alternative_start]:
        cell.font = Font(bold=True)
    sheet.column_dimensions["A"].width = 32
    sheet.column_dimensions["B"].width = 28
    sheet.column_dimensions["C"].width = 20
    sheet.column_dimensions["D"].width = 24
    for column in ("E", "F", "G", "H", "I"):
        sheet.column_dimensions[column].width = 24
    sheet.freeze_panes = "A2"

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="cotizacion_cintac.xlsx"'
    return response


def _quote_history_details(result, weight, weight_unit):
    option_fields = (
        "size",
        "capacity",
        "quantity",
        "recommended",
        "rate_currency",
        "unit_amount",
        "unit_amount_max",
        "currency",
        "amount",
        "amount_max",
        "source_currency",
        "source_amount_formatted",
        "source_amount_max_formatted",
    )
    comparison_fields = (
        "carrier",
        "unit_amount",
        "unit_amount_max",
        "rate_currency",
        "quantity",
        "amount",
        "amount_max",
        "currency",
        "days",
        "days_max",
        "route_type",
        "source",
    )
    return {
        "weight": weight,
        "weight_unit": weight_unit,
        "tonnes": result["tonnes"],
        "amount": result["amount"],
        "amount_max": result["amount_max"],
        "currency": result["currency"],
        "recommendation": result["recommendation"],
        "container_options": [
            {field: option[field] for field in option_fields}
            for option in result["container_options"]
        ],
        "base_days": result["base_days"],
        "base_days_max": result["base_days_max"],
        "margin_days": result["margin_days"],
        "total_days": result["total_days"],
        "total_days_max": result["total_days_max"],
        "converted": result["converted"],
        "exchange_rate": result["exchange_rate"],
        "exchange_rate_date": (
            result["exchange_rate_date"].strftime("%d/%m/%Y")
            if result["exchange_rate_date"]
            else ""
        ),
        "route_type": result["route_type"],
        "source": result["source"],
        "comparisons": [
            {field: comparison[field] for field in comparison_fields}
            for comparison in result["comparisons"]
        ],
        "comparison_unavailable": result["comparison_unavailable"],
    }


@never_cache
@login_required
def quote(request):
    # El cotizador ofrece únicamente tarifas de importación hacia los puertos admitidos.
    rates = list(
        FreightRate.objects.filter(operation="import")
        .filter(Q(destination_port="") | Q(destination_port__in=DESTINATIONS))
        .select_related("route")
    )
    for rate in rates:
        rate.freight_20_formatted = format_amount(rate.freight_20, rate.currency)
        rate.freight_20_max_formatted = (
            format_amount(rate.freight_20_max, rate.currency) if rate.freight_20_max is not None else ""
        )
        rate.freight_40_formatted = format_amount(rate.freight_40, rate.currency)
        rate.freight_40_max_formatted = (
            format_amount(rate.freight_40_max, rate.currency) if rate.freight_40_max is not None else ""
        )
    selected_rate_id = rates[0].pk if rates else ""
    # Valores iniciales del formulario que también se usan para solicitudes GET.
    form = {
        "rate_id": selected_rate_id,
        "destination": DESTINATIONS[0],
        "weight": "",
        "weight_unit": "kg",
        "margin_days": "0",
        "source_currency": rates[0].currency if rates else "",
        "target_currency": "",
        "exchange_rate": "",
    }
    result = None
    error = ""

    if request.method == "POST":
        # Mantiene solo los campos reconocidos por el formulario.
        for field in form:
            if field != "exchange_rate" and field in request.POST:
                form[field] = request.POST[field]
        try:
            if request.POST.get("transport", "sea") != "sea":
                raise ValueError("El cotizador solo permite transporte marítimo.")
            if not rates:
                raise ValueError("No hay tarifas de importación cargadas en los antecedentes.")
            if form["destination"] not in DESTINATIONS:
                raise ValueError("Selecciona uno de los destinos predefinidos.")

            rate = FreightRate.objects.select_related("route").get(
                pk=form["rate_id"],
                operation="import",
            )
            if rate.destination_port and rate.destination_port not in DESTINATIONS:
                raise ValueError("La tarifa seleccionada no corresponde a un puerto de importación permitido.")
            destination = rate.destination_port or form["destination"]
            if rate.destination_port and form["destination"] != rate.destination_port:
                form["destination"] = rate.destination_port

            tonnes, quantity_20 = container_count(form["weight"], form["weight_unit"], "20")
            _, quantity_40 = container_count(form["weight"], form["weight_unit"], "40")
            # Valida el margen de tránsito antes de sumarlo a los días base.
            try:
                margin_days = int(form["margin_days"])
            except (TypeError, ValueError) as exception:
                raise ValueError("Ingresa un margen de días entero y no negativo.") from exception
            if margin_days < 0:
                raise ValueError("El margen de días no puede ser negativo.")

            rate_currency = rate.currency
            source_currency = form["source_currency"] or rate_currency
            if source_currency not in {"CLP", "USD"}:
                raise ValueError("Selecciona CLP o USD como moneda desde la que convertir.")
            if rate_currency not in {"CLP", "USD"}:
                raise ValueError("La tarifa requiere una moneda definida como CLP o USD antes de convertir.")
            exchange_rate, exchange_rate_date = fetch_latest_usd_clp_rate()
            form["exchange_rate"] = str(exchange_rate)
            target_currency = {"USD": "CLP", "CLP": "USD"}[source_currency]
            form["target_currency"] = target_currency
            converted = True
            result_currency = target_currency

            container_options = []
            for size, quantity, unit_min, unit_max in (
                ("20", quantity_20, rate.freight_20, rate.freight_20_max),
                ("40", quantity_40, rate.freight_40, rate.freight_40_max),
            ):
                rate_amount_min = unit_min * quantity
                rate_amount_max = unit_max * quantity if unit_max is not None else None
                source_amount_min = convert_currency(
                    rate_amount_min,
                    rate_currency,
                    source_currency,
                    form["exchange_rate"],
                )
                source_amount_max = (
                    convert_currency(
                        rate_amount_max,
                        rate_currency,
                        source_currency,
                        form["exchange_rate"],
                    )
                    if rate_amount_max is not None
                    else None
                )
                amount_min = convert_currency(
                    source_amount_min,
                    source_currency,
                    target_currency,
                    form["exchange_rate"],
                )
                amount_max = (
                    convert_currency(
                        source_amount_max,
                        source_currency,
                        target_currency,
                        form["exchange_rate"],
                    )
                    if source_amount_max is not None
                    else None
                )
                container_options.append(
                    {
                        "size": size,
                        "capacity": "23" if size == "20" else "25",
                        "quantity": quantity,
                        "rate_amount": rate_amount_min,
                        "rate_amount_max": rate_amount_max,
                        "source_amount": source_amount_min,
                        "source_amount_max": source_amount_max,
                        "amount_value": amount_min,
                        "amount_max_value": amount_max,
                        "amount": format_amount(amount_min, target_currency),
                        "amount_max": format_amount(amount_max, target_currency) if amount_max is not None else "",
                        "source_amount_formatted": format_amount(source_amount_min, source_currency),
                        "source_amount_max_formatted": (
                            format_amount(source_amount_max, source_currency) if source_amount_max is not None else ""
                        ),
                        "unit_amount": format_amount(unit_min, rate_currency),
                        "unit_amount_max": format_amount(unit_max, rate_currency) if unit_max is not None else "",
                        "rate_currency": rate_currency,
                        "source_currency": source_currency,
                        "currency": target_currency,
                    }
                )

            recommended_option = min(
                container_options,
                key=lambda option: (option["amount_value"], option["size"] != "20"),
            )
            recommended_option["recommended"] = True
            for option in container_options:
                option.setdefault("recommended", False)
            quantity = recommended_option["quantity"]
            rate_amount_min = recommended_option["rate_amount"]
            rate_amount_max = recommended_option["rate_amount_max"]
            source_amount_min = recommended_option["source_amount"]
            source_amount_max = recommended_option["source_amount_max"]
            amount_min = recommended_option["amount_value"]
            amount_max = recommended_option["amount_max_value"]
            recommended_size = recommended_option["size"]

            # Calcula el tiempo total; el máximo solo existe si la tarifa tiene rango.
            base_days_max = rate.transit_days_max
            total_days_max = base_days_max + margin_days if base_days_max is not None else None

            # Prepara los datos formateados que consume el panel de resultado.
            result = {
                "rate": rate,
                "destination": destination,
                "tonnes": format_amount(tonnes),
                "quantity": quantity,
                "container_size": recommended_size,
                "container_options": container_options,
                "recommendation": {
                    "size": recommended_option["size"],
                    "quantity": recommended_option["quantity"],
                    "amount": recommended_option["amount"],
                    "currency": target_currency,
                },
                "base_days": rate.transit_days,
                "base_days_max": base_days_max,
                "margin_days": margin_days,
                "total_days": rate.transit_days + margin_days,
                "total_days_max": total_days_max,
                "amount": format_amount(amount_min, result_currency),
                "amount_max": format_amount(amount_max, result_currency) if amount_max is not None else "",
                "source_amount": recommended_option["source_amount_formatted"],
                "source_amount_max": recommended_option["source_amount_max_formatted"],
                "source_currency": source_currency,
                "rate_amount": format_amount(rate_amount_min, rate_currency),
                "rate_amount_max": format_amount(rate_amount_max, rate_currency) if rate_amount_max is not None else "",
                "rate_currency": rate_currency,
                "currency": result_currency,
                "converted": converted,
                "exchange_rate": format_amount(exchange_rate) if converted else "",
                "exchange_rate_date": exchange_rate_date if converted else "",
                "route_type": rate.route_type,
                "source": rate.source,
                "comparisons": [],
                "comparison_unavailable": "",
            }

            # Incluye tarifas generales para el origen junto con las del destino cotizado.
            alternatives = list(
                FreightRate.objects.filter(
                    operation=rate.operation,
                    route=rate.route,
                )
                .filter(Q(destination_port=destination) | Q(destination_port=""))
                .exclude(pk=rate.pk)
                .select_related("route")
            )
            if not alternatives:
                result["comparison_unavailable"] = "No hay otros embarcadores cargados para esta misma ruta."
            else:
                for alternative in alternatives:
                    alt_unit = alternative.freight_20 if recommended_size == "20" else alternative.freight_40
                    alt_unit_max = (
                        alternative.freight_20_max
                        if recommended_size == "20"
                        else alternative.freight_40_max
                    )
                    alternative_amount = convert_currency(
                        alt_unit * quantity,
                        alternative.currency,
                        target_currency,
                        form["exchange_rate"],
                    )
                    alternative_amount_max = (
                        convert_currency(
                            alt_unit_max * quantity,
                            alternative.currency,
                            target_currency,
                            form["exchange_rate"],
                        )
                        if alt_unit_max is not None
                        else None
                    )
                    result["comparisons"].append(
                        {
                            "rate_id": alternative.pk,
                            "carrier": alternative.carrier or "Sin especificar",
                            "unit_amount": format_amount(alt_unit, alternative.currency),
                            "unit_amount_max": (
                                format_amount(alt_unit_max, alternative.currency)
                                if alt_unit_max is not None
                                else ""
                            ),
                            "rate_currency": alternative.currency,
                            "quantity": quantity,
                            "amount": format_amount(alternative_amount, target_currency or alternative.currency),
                            "amount_max": (
                                format_amount(alternative_amount_max, target_currency)
                                if alternative_amount_max is not None
                                else ""
                            ),
                            "currency": target_currency or alternative.currency,
                            "amount_value": alternative_amount,
                            "days": alternative.transit_days + margin_days,
                            "days_max": (
                                alternative.transit_days_max + margin_days
                                if alternative.transit_days_max is not None
                                else None
                            ),
                            "route_type": alternative.route_type,
                            "source": alternative.source,
                        }
                    )
                result["comparisons"].sort(key=lambda item: item["amount_value"])

            if not request.POST.get("export_excel"):
                QuoteHistory.objects.create(
                    user=request.user,
                    rate=rate,
                    operation=rate.operation,
                    origin_port=rate.route.origin_port,
                    origin_country=rate.route.country,
                    destination=destination,
                    carrier=rate.carrier,
                    container_size=recommended_size,
                    weight=Decimal(form["weight"]),
                    weight_unit=form["weight_unit"],
                    tonnes=tonnes,
                    container_quantity=quantity,
                    margin_days=margin_days,
                    source_currency=source_currency,
                    currency=result_currency,
                    exchange_rate=Decimal(form["exchange_rate"]),
                    source_amount=source_amount_min,
                    source_amount_max=source_amount_max,
                    rate_currency=rate_currency,
                    rate_amount=rate_amount_min,
                    rate_amount_max=rate_amount_max,
                    amount=amount_min,
                    amount_max=amount_max,
                    base_days=rate.transit_days,
                    base_days_max=base_days_max,
                    total_days=rate.transit_days + margin_days,
                    total_days_max=total_days_max,
                    details=_quote_history_details(
                        result,
                        form["weight"],
                        form["weight_unit"],
                    ),
                )
        except FreightRate.DoesNotExist:
            # La tarifa enviada ya no existe o no corresponde a un registro válido.
            error = (
                "No hay tarifas de importación cargadas en los antecedentes."
                if not rates
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
            "destinations": list(DESTINATIONS),
            "form": form,
            "selected_rate_id": selected_rate_id,
            "result": result,
            "error": error,
            "no_rates_message": (
                "No hay tarifas de importación cargadas en los antecedentes."
                if not rates and request.method == "GET"
                else ""
            ),
        },
    )


@never_cache
@login_required
def user_profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = UserProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Tu perfil se actualizó correctamente.")
            return redirect("user_profile")
    else:
        form = UserProfileForm(instance=profile)

    return render(request, "cotizador/profile.html", {"form": form})


@never_cache
@user_manager_required
def manage_users(request):
    search = request.GET.get("q", "").strip()
    queryset = _manageable_users(request.user)
    if search:
        queryset = queryset.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
            | Q(profile__rut__icontains=search)
        )

    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "cotizador/manage_users.html",
        {
            "page_obj": page,
            "users": page.object_list,
            "search": search,
            "total_users": page.paginator.count,
        },
    )


def _manageable_users(manager):
    User = get_user_model()
    return (
        User.objects.select_related("profile")
        .exclude(pk=manager.pk)
        .exclude(is_superuser=True)
        .exclude(groups__name=TARIFF_ADMIN_GROUP)
        .distinct()
        .order_by("username")
    )


@never_cache
@user_manager_required
def create_managed_user(request):
    if request.method == "POST":
        form = ManagedUserCreateForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save()
            messages.success(request, f"Se creó el usuario {user.username}.")
            return redirect("manage_users")
    else:
        form = ManagedUserCreateForm()
    return render(
        request,
        "cotizador/managed_user_form.html",
        {"form": form, "editing": False},
    )


@never_cache
@user_manager_required
def edit_managed_user(request, user_id):
    target_user = get_object_or_404(_manageable_users(request.user), pk=user_id)
    if request.method == "POST":
        form = ManagedUserUpdateForm(request.POST, instance=target_user)
        if form.is_valid():
            with transaction.atomic():
                user = form.save()
            messages.success(request, f"Se actualizaron los datos de {user.username}.")
            return redirect("manage_users")
    else:
        form = ManagedUserUpdateForm(instance=target_user)
    return render(
        request,
        "cotizador/managed_user_form.html",
        {"form": form, "editing": True, "managed_user": target_user},
    )


@never_cache
@user_manager_required
@require_POST
def delete_managed_user(request, user_id):
    target_user = get_object_or_404(_manageable_users(request.user), pk=user_id)
    username = target_user.get_username()
    target_user.delete()
    messages.success(
        request,
        f"Se eliminó el usuario {username} junto con sus cotizaciones e historial.",
    )
    return redirect("manage_users")


@never_cache
@login_required
def quote_history(request):
    history = QuoteHistory.objects.select_related("user")
    if not can_view_all_quotes(request.user):
        history = history.filter(user=request.user)
    page = Paginator(
        history,
        20,
    ).get_page(request.GET.get("page"))
    return render(
        request,
        "cotizador/history.html",
        {
            "page_obj": page,
            "quote_rows": [
                {
                    "quote": quote,
                    "amount": format_amount(quote.amount, quote.currency),
                    "amount_max": format_amount(quote.amount_max, quote.currency) if quote.amount_max is not None else "",
                    "source_amount": (
                        format_amount(quote.source_amount, quote.source_currency)
                        if quote.source_amount is not None
                        else ""
                    ),
                    "source_amount_max": (
                        format_amount(quote.source_amount_max, quote.source_currency)
                        if quote.source_amount_max is not None
                        else ""
                    ),
                    "rate_amount": format_amount(quote.rate_amount, quote.rate_currency)
                    if quote.rate_amount is not None
                    else "",
                    "rate_amount_max": format_amount(quote.rate_amount_max, quote.rate_currency)
                    if quote.rate_amount_max is not None
                    else "",
                    "tonnes": format_amount(quote.tonnes),
                    "detail_url": reverse("quote_history_detail", args=(quote.pk,)),
                }
                for quote in page.object_list
            ],
            "total_quotes": page.paginator.count,
            "can_manage_history": can_view_all_quotes(request.user),
            "can_clear_history": is_user_manager(request.user),
        },
    )


def _legacy_quote_details(quote):
    quantity = quote.container_quantity
    rate_amount = quote.rate_amount / quantity if quote.rate_amount is not None else None
    rate_amount_max = (
        quote.rate_amount_max / quantity
        if quote.rate_amount_max is not None
        else None
    )
    return {
        "weight": format_amount(quote.weight),
        "weight_unit": quote.weight_unit,
        "tonnes": format_amount(quote.tonnes),
        "amount": format_amount(quote.amount, quote.currency),
        "amount_max": (
            format_amount(quote.amount_max, quote.currency)
            if quote.amount_max is not None
            else ""
        ),
        "currency": quote.currency,
        "recommendation": {
            "size": quote.container_size,
            "quantity": quantity,
            "amount": format_amount(quote.amount, quote.currency),
            "currency": quote.currency,
        },
        "container_options": [
            {
                "size": quote.container_size,
                "capacity": "23" if quote.container_size == "20" else "25",
                "quantity": quantity,
                "recommended": True,
                "rate_currency": quote.rate_currency,
                "unit_amount": (
                    format_amount(rate_amount, quote.rate_currency)
                    if rate_amount is not None
                    else ""
                ),
                "unit_amount_max": (
                    format_amount(rate_amount_max, quote.rate_currency)
                    if rate_amount_max is not None
                    else ""
                ),
                "currency": quote.currency,
                "amount": format_amount(quote.amount, quote.currency),
                "amount_max": (
                    format_amount(quote.amount_max, quote.currency)
                    if quote.amount_max is not None
                    else ""
                ),
                "source_currency": quote.source_currency,
                "source_amount_formatted": (
                    format_amount(quote.source_amount, quote.source_currency)
                    if quote.source_amount is not None
                    else ""
                ),
                "source_amount_max_formatted": (
                    format_amount(quote.source_amount_max, quote.source_currency)
                    if quote.source_amount_max is not None
                    else ""
                ),
            }
        ],
        "base_days": quote.base_days,
        "base_days_max": quote.base_days_max,
        "margin_days": quote.margin_days,
        "total_days": quote.total_days,
        "total_days_max": quote.total_days_max,
        "converted": quote.exchange_rate is not None,
        "exchange_rate": str(quote.exchange_rate or ""),
        "exchange_rate_date": "",
        "route_type": "",
        "source": "",
        "comparisons": [],
        "comparison_unavailable": (
            "Esta cotización se guardó antes de habilitar el detalle completo. "
            "El historial conserva el total y la opción recomendada, pero no las "
            "alternativas ni la comparación de ambos tamaños."
        ),
        "is_complete_snapshot": False,
    }


@never_cache
@login_required
def quote_history_detail(request, quote_id):
    quotes = QuoteHistory.objects.select_related("user")
    if not can_view_all_quotes(request.user):
        quotes = quotes.filter(user=request.user)
    saved_quote = get_object_or_404(quotes, pk=quote_id)
    details = saved_quote.details or _legacy_quote_details(saved_quote)
    if "is_complete_snapshot" not in details:
        details["is_complete_snapshot"] = True
    return render(
        request,
        "cotizador/history_detail.html",
        {
            "quote": saved_quote,
            "details": details,
        },
    )


@never_cache
@login_required
def quote_history_excel(request, quote_id):
    quotes = QuoteHistory.objects.select_related("user")
    if not can_view_all_quotes(request.user):
        quotes = quotes.filter(user=request.user)
    quote = get_object_or_404(quotes, pk=quote_id)
    details = quote.details or _legacy_quote_details(quote)
    recommendation = details.get("recommendation", {})
    username = quote.user.get_full_name() or quote.user.get_username()
    rows = [
        ["CINTAC | Cotización marítima"],
        ["Operación", "Importación"],
        ["Usuario", username],
        ["Fecha", quote.created_at.strftime("%d/%m/%Y %H:%M")],
        ["Origen", quote.origin_port, quote.origin_country],
        ["Destino", quote.destination],
        ["Embarcador", quote.carrier or "Sin especificar"],
        ["Tipo de ruta", details.get("route_type") or "Sin especificar"],
        ["Fuente", details.get("source") or "Sin especificar"],
        ["Peso informado", details.get("weight", format_amount(quote.weight)), quote.weight_unit],
        ["Peso convertido", details.get("tonnes", format_amount(quote.tonnes)), "TN"],
        ["Tamaño recomendado", f'{recommendation.get("size", quote.container_size)} pies'],
        [
            "Recomendación económica",
            (
                f'{recommendation.get("quantity", quote.container_quantity)} contenedor(es) '
                f'de {recommendation.get("size", quote.container_size)} pies'
            ),
            f'{recommendation.get("currency", quote.currency)} '
            f'{recommendation.get("amount", format_amount(quote.amount, quote.currency))}',
        ],
        ["Flete total mínimo", details.get("amount", format_amount(quote.amount, quote.currency)), quote.currency],
        [
            "Flete total máximo",
            details.get(
                "amount_max",
                format_amount(quote.amount_max, quote.currency) if quote.amount_max is not None else "Sin máximo",
            ) or "Sin máximo",
            quote.currency,
        ],
        ["Tránsito base mínimo", quote.base_days, "días"],
        [
            "Tránsito base máximo",
            quote.base_days_max if quote.base_days_max is not None else "Sin máximo",
            "días",
        ],
        ["Margen agregado", quote.margin_days, "días"],
        ["Tránsito estimado mínimo", quote.total_days, "días"],
        [
            "Tránsito estimado máximo",
            quote.total_days_max if quote.total_days_max is not None else "Sin máximo",
            "días",
        ],
    ]
    if quote.exchange_rate is not None:
        rows.append(["Tipo de cambio aplicado", details.get("exchange_rate") or str(quote.exchange_rate), "CLP por USD"])
        if details.get("exchange_rate_date"):
            rows.append(["Fecha del tipo de cambio", details["exchange_rate_date"]])

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Cotización"
    for row in rows:
        sheet.append(row)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"

    sheet.append([])
    container_section = sheet.max_row + 1
    sheet.append(["Comparativa de presupuesto por tamaño de contenedor"])
    sheet.append(
        [
            "Contenedor",
            "Cantidad",
            "Capacidad máxima por unidad",
            "Tarifa unitaria mínimo",
            "Tarifa unitaria máximo",
            "Moneda tarifa",
            "Total cotización mínimo",
            "Total cotización máximo",
            "Moneda cotización",
        ]
    )
    for option in details.get("container_options", []):
        sheet.append(
            [
                f'{option.get("size", "")} pies',
                option.get("quantity", ""),
                f'{option.get("capacity", "Sin especificar")} TN',
                option.get("unit_amount") or "Sin especificar",
                option.get("unit_amount_max") or "Sin máximo",
                option.get("rate_currency", quote.rate_currency),
                option.get("amount", ""),
                option.get("amount_max") or "Sin máximo",
                option.get("currency", quote.currency),
            ]
        )

    alternative_section = sheet.max_row + 2
    sheet.append([])
    sheet.append(["Comparación de alternativas de embarcador"])
    sheet.append(
        [
            "Embarcador",
            "Tarifa unitaria mínima",
            "Tarifa unitaria máxima",
            "Moneda tarifa",
            "Cantidad de contenedores",
            "Total estimado mínimo",
            "Total estimado máximo",
            "Moneda cotización",
            "Tránsito estimado mínimo",
            "Tránsito estimado máximo",
            "Tipo de ruta",
            "Fuente",
        ]
    )
    for item in details.get("comparisons", []):
        sheet.append(
            [
                item.get("carrier", "Sin especificar"),
                item.get("unit_amount", ""),
                item.get("unit_amount_max") or "Sin máximo",
                item.get("rate_currency", ""),
                item.get("quantity", ""),
                item.get("amount", ""),
                item.get("amount_max") or "Sin máximo",
                item.get("currency", ""),
                item.get("days", ""),
                item.get("days_max") if item.get("days_max") is not None else "Sin máximo",
                item.get("route_type") or "Sin especificar",
                item.get("source") or "Sin especificar",
            ]
        )
    for row in sheet.iter_rows(min_row=container_section, max_row=sheet.max_row):
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"

    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF", size=14)
        cell.fill = PatternFill("solid", fgColor="E96F00")
    for row_index in (container_section, alternative_section):
        for cell in sheet[row_index]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="303030")
        for cell in sheet[row_index + 1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="FFF1DF")
    for column, width in {"A": 34, "B": 28, "C": 24, "D": 25}.items():
        sheet.column_dimensions[column].width = width
    for column in ("E", "F", "G", "H", "I", "J", "K", "L"):
        sheet.column_dimensions[column].width = 24
    sheet.freeze_panes = "A2"

    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="cotizacion_cintac_{quote.pk}.xlsx"'
    return response


@never_cache
@user_manager_required
@require_POST
def clear_quote_history(request):
    if request.POST.get("confirm_delete") != "yes":
        messages.error(request, "Confirma que deseas eliminar todo el historial. No se eliminó ninguna cotización.")
        return redirect("quote_history")

    password = request.POST.get("password", "")
    if not password or not request.user.check_password(password):
        messages.error(request, "La contraseña ingresada no es correcta. No se eliminó el historial.")
        return redirect("quote_history")

    deleted_count, _ = QuoteHistory.objects.all().delete()
    messages.success(
        request,
        f"Se eliminaron {deleted_count} cotizaciones de todo el historial.",
    )
    return redirect("quote_history")


@never_cache
@login_required
def rates(request):
    search = request.GET.get("q", "").strip()
    queryset = (
        FreightRate.objects.filter(operation="import")
        .filter(Q(destination_port="") | Q(destination_port__in=DESTINATIONS))
        .select_related("route")
    )
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
            "freight_20": format_amount(rate.freight_20, rate.currency),
            "freight_20_max": format_amount(rate.freight_20_max, rate.currency) if rate.freight_20_max is not None else "",
            "freight_40": format_amount(rate.freight_40, rate.currency),
            "freight_40_max": format_amount(rate.freight_40_max, rate.currency) if rate.freight_40_max is not None else "",
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
            "can_add_rates": is_tariff_admin(request.user),
            "can_edit_rates": is_tariff_admin(request.user),
            "can_delete_rates": is_tariff_admin(request.user),
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
@tariff_admin_required
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
                    "Ya existe una tarifa para esta ruta, destino y embarcador.",
                )
            else:
                messages.success(request, "Tarifa de importación guardada correctamente.")
                return redirect("rates")
    else:
        form = FreightRateEntryForm()
    return render(request, "cotizador/rate_form.html", {"form": form, "editing": False})


@never_cache
@tariff_admin_required
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
                    "Tarifa de importación actualizada correctamente.",
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
    route_type, _, route_id = value.partition(":")
    if route_type != "route" or not route_id:
        raise ValueError("Selecciona una ruta de origen válida.")
    return get_object_or_404(Route, pk=route_id, country__isnull=False)


@never_cache
@tariff_admin_required
def rate_delete(request, rate_id):
    rate = get_object_or_404(
        FreightRate.objects.select_related("route"),
        pk=rate_id,
    )
    if request.method == "POST":
        description = str(rate)
        rate.delete()
        messages.success(request, f"Tarifa de importación eliminada: {description}.")
        return redirect("rates")
    return render(
        request,
        "cotizador/rate_confirm_delete.html",
        {
            "rate": rate,
            "freight_20": format_amount(rate.freight_20, rate.currency),
            "freight_40": format_amount(rate.freight_40, rate.currency),
        },
    )
