import re
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError

from .models import FreightRate, Route, UserProfile
from .services import DESTINATIONS, format_amount


USD_RATE_MAX = 20_000
USD_RATE_STEP = 50
CLP_RATE_MAX = 20_000_000
CLP_RATE_STEP = 10_000
TRANSIT_DAYS = range(1, 121)
MANUAL_SOURCE = "Tarifa ingresada por administración"


class CintacAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "El usuario o la contraseña no son correctos.",
        "inactive": "Esta cuenta está inactiva.",
    }


class UserProfileForm(forms.ModelForm):
    first_name = forms.CharField(label="Nombre", max_length=150)
    last_name = forms.CharField(label="Apellidos", max_length=150, required=False)
    email = forms.EmailField(label="Correo electrónico")

    class Meta:
        model = UserProfile
        fields = ("rut", "avatar")
        labels = {"rut": "RUT (opcional)", "avatar": "Foto de perfil"}
        widgets = {
            "avatar": forms.FileInput(
                attrs={"accept": "image/*", "id": "profile-avatar-input", "hidden": True}
            ),
            "rut": forms.TextInput(attrs={"placeholder": "12.345.678-9"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.instance.user
        self.fields["first_name"].initial = user.first_name
        self.fields["last_name"].initial = user.last_name
        self.fields["email"].initial = user.email

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if self.data.get("avatar-clear") == "on" and not self.files.get("avatar"):
            return False
        if avatar and avatar.size > 5 * 1024 * 1024:
            raise forms.ValidationError("La foto no puede superar 5 MB.")
        return avatar

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        if commit:
            profile.save()
            user.save(update_fields=["first_name", "last_name", "email"])
        return profile


class ManagedUserCreateForm(UserCreationForm):
    email = forms.EmailField(label="Correo electrónico")
    first_name = forms.CharField(label="Nombre", max_length=150)
    last_name = forms.CharField(label="Apellido", max_length=150)
    rut = forms.CharField(
        label="RUT",
        max_length=12,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "12.345.678-9"}),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email", "first_name", "last_name")

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ya existe una cuenta con este nombre de usuario.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo electrónico.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            UserProfile.objects.update_or_create(
                user=user,
                defaults={"rut": self.cleaned_data["rut"].strip()},
            )
        return user


class ManagedUserUpdateForm(forms.ModelForm):
    email = forms.EmailField(label="Correo electrónico")
    first_name = forms.CharField(label="Nombre", max_length=150)
    last_name = forms.CharField(label="Apellido", max_length=150)
    rut = forms.CharField(
        label="RUT",
        max_length=12,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "12.345.678-9"}),
    )
    password1 = forms.CharField(
        label="Nueva contraseña",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirmar contraseña",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "email", "first_name", "last_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rut"].initial = self.instance.profile.rut

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        User = get_user_model()
        if User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe una cuenta con este nombre de usuario.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        User = get_user_model()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo electrónico.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password1")
        password_confirmation = cleaned_data.get("password2")
        if password or password_confirmation:
            if password != password_confirmation:
                self.add_error("password2", "Las contraseñas no coinciden.")
            elif password:
                user = self.instance
                for field in ("username", "email", "first_name", "last_name"):
                    if field in cleaned_data:
                        setattr(user, field, cleaned_data[field])
                try:
                    password_validation.validate_password(password, user=user)
                except ValidationError as error:
                    self.add_error("password1", error)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
        if commit:
            user.save()
            UserProfile.objects.update_or_create(
                user=user,
                defaults={"rut": self.cleaned_data["rut"].strip()},
            )
        return user


class ImportRouteAdminForm(forms.ModelForm):
    class Meta:
        model = Route
        fields = ("country", "origin_port")

    def clean_country(self):
        country = self.cleaned_data["country"].strip()
        if country.casefold() == "chile":
            raise forms.ValidationError("El origen de una importación debe estar fuera de Chile.")
        return country


class TariffExcelUploadForm(forms.Form):
    workbook = forms.FileField(
        label="Archivo Excel (.xlsx)",
        help_text="Carga el libro con la hoja Importaciones.",
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
        help_text="Elige un puerto internacional para importar.",
    )

    class Meta:
        model = FreightRate
        fields = (
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
        routes = list(
            Route.objects.filter(rates__operation="import")
            .exclude(country="Chile")
            .distinct()
        )
        routes.sort(key=lambda route: (route.country, route.origin_port))
        choices = [
            (
                f"route:{route.pk}",
                f"{route.origin_port}, {route.country}",
            )
            for route in routes
        ]
        self.fields["origin_route"].choices = choices
        self.fields["origin_route"].widget.choices = choices
        if self.instance.pk:
            self.initial["origin_route"] = f"route:{self.instance.route_id}"
        elif choices:
            self.initial["origin_route"] = choices[0][0]

    def _configure_destination_choices(self):
        destinations = [("", "Sin destino definido")]
        destinations.extend((port, f"{port}, Chile") for port in DESTINATIONS)
        self.fields["destination_port"].widget = forms.Select()
        self.fields["destination_port"].choices = destinations
        self.fields["destination_port"].widget.choices = destinations
        self.fields["destination_port"].help_text = "Elige Valparaíso o San Antonio."

    def _configure_catalog_choices(self):
        carriers = list(
            FreightRate.objects.exclude(carrier="")
            .values_list("carrier", flat=True)
            .distinct()
            .order_by("carrier")
        )
        carrier_choices = [("", "Sin especificar")]
        carrier_choices.extend((carrier, carrier) for carrier in carriers)
        self.fields["carrier"] = forms.ChoiceField(
            label=self.fields["carrier"].label,
            choices=carrier_choices,
            required=False,
            widget=forms.Select(),
        )
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
            (f"{value:.2f}", format_amount(Decimal(value), currency))
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
        destination = cleaned_data.get("destination_port", "")
        if destination and destination not in DESTINATIONS:
            self.add_error("destination_port", "La importación solo admite Valparaíso o San Antonio.")

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
