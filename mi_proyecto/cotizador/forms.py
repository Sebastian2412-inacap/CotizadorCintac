import re
from decimal import Decimal

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import FreightRate, Route
from .services import DESTINATIONS, format_amount


USD_RATE_MAX = 20_000
USD_RATE_STEP = 50
CLP_RATE_MAX = 20_000_000
CLP_RATE_STEP = 10_000
TRANSIT_DAYS = range(1, 121)
CHILE_ORIGIN_PORTS = DESTINATIONS
MANUAL_SOURCE = "Tarifa ingresada por administración"


class CintacAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "El usuario o la contraseña no son correctos.",
        "inactive": "Esta cuenta está inactiva.",
    }


class TariffExcelUploadForm(forms.Form):
    workbook = forms.FileField(
        label="Archivo Excel (.xlsx)",
        help_text="Carga el libro con las hojas Importaciones y Exportaciones.",
    )

    def clean_workbook(self):
        workbook = self.cleaned_data["workbook"]
        if not workbook.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("El archivo debe tener formato .xlsx.")
        if len(workbook.name) > 150:
            raise forms.ValidationError("El nombre del archivo no puede superar 150 caracteres.")
        if workbook.size > 5 * 1024 * 1024:
            raise forms.ValidationError("El archivo no puede superar 5 MB.")
        return workbook


class FreightRateEntryForm(forms.ModelForm):
    origin_route = forms.ChoiceField(
        label="País y puerto de origen",
        help_text="Elige un origen internacional para importar o un puerto chileno para exportar.",
    )

    class Meta:
        model = FreightRate
        fields = (
            "operation",
            "destination_port",
            "carrier",
            "route_type",
            "transit_days",
            "transit_days_max",
            "freight_20",
            "freight_20_max",
            "freight_40",
            "freight_40_max",
            "currency",
            "source",
        )
        labels = {
            "operation": "Tipo de operación",
            "destination_port": "Puerto de destino",
            "carrier": "Embarcador",
            "route_type": "Tipo de ruta",
            "transit_days": "Tránsito mínimo/base (días)",
            "transit_days_max": "Tránsito máximo (días)",
            "freight_20": "Flete 20 pies",
            "freight_20_max": "Flete máximo 20 pies",
            "freight_40": "Flete 40 pies",
            "freight_40_max": "Flete máximo 40 pies",
            "currency": "Moneda",
            "source": "Fuente / referencia",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_route_choices()
        self._configure_destination_choices()
        self._configure_catalog_choices()
        self._configure_numeric_choices()

    def _configure_route_choices(self):
        routes = list(Route.objects.filter(rates__isnull=False).distinct())
        routes.sort(key=lambda route: (route.country == "Chile", route.country, route.origin_port))
        choices = [
            (
                f"route:{route.pk}",
                f"{'Exportación' if route.country == 'Chile' else 'Importación'}: "
                f"{route.origin_port}, {route.country}",
            )
            for route in routes
        ]
        known_routes = {(route.country, route.origin_port) for route in routes}
        for port in CHILE_ORIGIN_PORTS:
            if ("Chile", port) not in known_routes:
                choices.append((f"catalog:Chile|{port}", f"{port}, Chile"))
        self.fields["origin_route"].choices = choices
        self.fields["origin_route"].widget.choices = choices
        if self.instance.pk:
            self.initial["origin_route"] = f"route:{self.instance.route_id}"
        elif choices:
            self.initial["origin_route"] = choices[0][0]

    def _configure_destination_choices(self):
        destinations = [("", "Sin destino definido")]
        destinations.extend((port, f"{port}, Chile") for port in DESTINATIONS)
        for route in Route.objects.filter(rates__isnull=False).exclude(country="Chile").distinct().order_by(
            "country", "origin_port"
        ):
            destinations.append((f"{route.origin_port}, {route.country}", f"{route.origin_port}, {route.country}"))

        current_destination = self.instance.destination_port if self.instance.pk else ""
        values = {value for value, _ in destinations}
        if current_destination and current_destination not in values:
            destinations.append((current_destination, current_destination))
        self.fields["destination_port"].widget = forms.Select()
        self.fields["destination_port"].choices = destinations
        self.fields["destination_port"].widget.choices = destinations
        self.fields["destination_port"].help_text = (
            "Elige un puerto chileno para importación o un puerto internacional para exportación."
        )

    def _configure_catalog_choices(self):
        carriers = list(
            FreightRate.objects.exclude(carrier="")
            .values_list("carrier", flat=True)
            .distinct()
            .order_by("carrier")
        )
        carrier_choices = [("", "Sin especificar")]
        carrier_choices.extend((carrier, carrier) for carrier in carriers)
        self.fields["carrier"].widget = forms.Select()
        self.fields["carrier"].choices = carrier_choices
        self.fields["carrier"].widget.choices = carrier_choices
        if not carriers:
            self.fields["carrier"].help_text = "No hay embarcadores registrados; deja «Sin especificar»."

        route_types = list(
            FreightRate.objects.exclude(route_type="")
            .values_list("route_type", flat=True)
            .distinct()
            .order_by("route_type")
        )
        for route_type in ("Directo", "Transbordo"):
            if route_type not in route_types:
                route_types.append(route_type)
        route_type_choices = [("", "Sin especificar")] + [
            (route_type, route_type) for route_type in route_types
        ]
        self.fields["route_type"].widget = forms.Select()
        self.fields["route_type"].choices = route_type_choices
        self.fields["route_type"].widget.choices = route_type_choices

        sources = list(
            FreightRate.objects.exclude(source="")
            .values_list("source", flat=True)
            .distinct()
            .order_by("source")
        )
        if MANUAL_SOURCE not in sources:
            sources.append(MANUAL_SOURCE)
        source_choices = [("", "Sin especificar")] + [
            (source, self._source_label(source)) for source in sources
        ]
        self.fields["source"].widget = forms.Select()
        self.fields["source"].choices = source_choices
        self.fields["source"].widget.choices = source_choices

    def _configure_numeric_choices(self):
        currency = self.data.get("currency") if self.is_bound else self.instance.currency
        currency = currency or "USD"
        if currency == "CLP":
            maximum, step = CLP_RATE_MAX, CLP_RATE_STEP
        else:
            maximum, step = USD_RATE_MAX, USD_RATE_STEP

        amounts = [
            (f"{value:.2f}", format_amount(Decimal(value)))
            for value in range(0, maximum + 1, step)
        ]
        for field_name in ("freight_20", "freight_40"):
            self.fields[field_name] = forms.TypedChoiceField(
                label=self.fields[field_name].label,
                choices=amounts,
                coerce=Decimal,
                widget=forms.Select(),
            )
        for field_name in ("freight_20_max", "freight_40_max"):
            self.fields[field_name] = forms.TypedChoiceField(
                label=self.fields[field_name].label,
                choices=[("", "Sin máximo"), *amounts],
                coerce=Decimal,
                required=False,
                empty_value=None,
                widget=forms.Select(),
            )

        transit_choices = [(day, f"{day} días") for day in TRANSIT_DAYS]
        self.fields["transit_days"] = forms.TypedChoiceField(
            label=self.fields["transit_days"].label,
            choices=transit_choices,
            coerce=int,
            widget=forms.Select(),
        )
        self.fields["transit_days_max"] = forms.TypedChoiceField(
            label=self.fields["transit_days_max"].label,
            choices=[("", "Sin máximo"), *transit_choices],
            coerce=int,
            required=False,
            empty_value=None,
            widget=forms.Select(),
        )

    @staticmethod
    def _source_label(source):
        if source == MANUAL_SOURCE:
            return source
        match = re.search(r"Importaciones!A(\d+):H\d+", source)
        if match:
            return f"Excel de tarifas · Importaciones, fila {match.group(1)}"
        return source

    def clean(self):
        cleaned_data = super().clean()
        operation = cleaned_data.get("operation")
        destination = cleaned_data.get("destination_port", "")
        if operation == "export" and not destination:
            self.add_error("destination_port", "La exportación requiere un puerto de destino.")
        origin_route = cleaned_data.get("origin_route", "")
        if operation == "export" and origin_route.startswith("catalog:"):
            country = origin_route.partition(":")[2].partition("|")[0]
            if country != "Chile":
                self.add_error("origin_route", "El origen de una exportación debe estar en Chile.")
        elif operation == "export" and origin_route.startswith("route:"):
            route_id = origin_route.partition(":")[2]
            if not Route.objects.filter(pk=route_id, country="Chile").exists():
                self.add_error("origin_route", "El origen de una exportación debe estar en Chile.")

        for minimum_name, maximum_name in (
            ("freight_20", "freight_20_max"),
            ("freight_40", "freight_40_max"),
            ("transit_days", "transit_days_max"),
        ):
            minimum = cleaned_data.get(minimum_name)
            maximum = cleaned_data.get(maximum_name)
            if minimum is not None and maximum is not None and maximum < minimum:
                self.add_error(maximum_name, "El máximo no puede ser menor que el mínimo.")
        return cleaned_data
