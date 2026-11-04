# Herramientas de administración de Django para gestionar las tarifas y rutas.
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import path, reverse

# Formulario, validación e importación transaccional del Excel de tarifas.
from .excel_import import TariffImportError, import_tariff_workbook
from .forms import ImportRouteAdminForm, TariffExcelUploadForm

# Modelos que se mostrarán en el sitio de administración.
from .models import FreightRate, QuoteHistory, Route
from .permissions import is_tariff_admin, is_user_manager


# Permite editar tarifas relacionadas desde la misma pantalla de una ruta.
class FreightRateInline(admin.TabularInline):
    # Modelo de tarifas subordinadas a la ruta seleccionada.
    model = FreightRate
    # No agrega filas vacías de tarifas automáticamente.
    extra = 0
    # Campos de tarifa visibles en la edición en línea.
    exclude = ("operation",)
    fields = (
        "destination_port", "carrier", "route_type", "transit_days", "transit_days_max",
        "freight_20", "freight_20_max", "freight_40", "freight_40_max", "currency", "source",
    )

    def has_view_permission(self, request, obj=None):
        return is_tariff_admin(request.user)

    def has_add_permission(self, request, obj=None):
        return is_tariff_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_tariff_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_tariff_admin(request.user)


class TariffManagerAdminMixin:
    def has_module_permission(self, request):
        return is_tariff_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return is_tariff_admin(request.user)

    def has_add_permission(self, request):
        return is_tariff_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_tariff_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return is_tariff_admin(request.user)


# Registra las rutas y configura cómo se buscan y editan en el admin.
@admin.register(Route)
class RouteAdmin(TariffManagerAdminMixin, admin.ModelAdmin):
    form = ImportRouteAdminForm
    # Columnas visibles en el listado de rutas.
    list_display = ("country", "origin_port")
    # Filtro lateral para limitar rutas por país.
    list_filter = ("country",)
    # Campos consultados por el buscador del administrador.
    search_fields = ("country", "origin_port")
    # Integra las tarifas en la pantalla de cada ruta.
    inlines = (FreightRateInline,)


# Registra las tarifas como una sección administrable independiente.
@admin.register(FreightRate)
class FreightRateAdmin(TariffManagerAdminMixin, admin.ModelAdmin):
    change_list_template = "admin/cotizador/freightrate/change_list.html"
    exclude = ("operation",)

    # Columnas útiles para revisar montos, rangos y actualización.
    list_display = (
        "route", "destination_port", "carrier", "transit_days", "transit_days_max",
        "freight_20", "freight_20_max", "freight_40", "freight_40_max", "currency", "source", "updated_at",
    )
    # Filtros para acotar tarifas por moneda, país, destino o tipo de ruta.
    list_filter = ("currency", "route__country", "destination_port", "route_type")
    # Campos locales y de la ruta asociados al texto de búsqueda.
    search_fields = ("route__country", "route__origin_port", "destination_port", "carrier", "source")

    def get_urls(self):
        info = self.opts.app_label, self.opts.model_name
        custom_urls = [
            path(
                "import-excel/",
                self.admin_site.admin_view(self.import_excel_view),
                name="%s_%s_import_excel" % info,
            ),
        ]
        return custom_urls + super().get_urls()

    def import_excel_view(self, request):
        if not is_tariff_admin(request.user):
            raise PermissionDenied

        if request.method == "POST":
            form = TariffExcelUploadForm(request.POST, request.FILES)
            if form.is_valid():
                try:
                    result = import_tariff_workbook(form.cleaned_data["workbook"])
                except TariffImportError as error:
                    form.add_error("workbook", str(error))
                else:
                    summary = (
                        f"Excel procesado: {result.created} tarifas nuevas y "
                        f"{result.updated} actualizadas. Moneda aplicada: USD."
                    )
                    messages.success(request, summary)
                    return redirect(
                        reverse(
                            "admin:%s_%s_changelist"
                            % (self.opts.app_label, self.opts.model_name)
                        )
                    )
        else:
            form = TariffExcelUploadForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Vincular tarifas desde Excel",
            "opts": self.opts,
            "form": form,
        }
        return render(request, "admin/cotizador/import_excel.html", context)


@admin.register(QuoteHistory)
class QuoteHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "user",
        "origin_country",
        "origin_port",
        "destination",
        "weight",
        "weight_unit",
        "amount",
        "currency",
    )
    list_filter = ("created_at", "operation", "currency", "weight_unit")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "origin_country",
        "origin_port",
        "destination",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-pk")

    def has_module_permission(self, request):
        return is_tariff_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return is_tariff_admin(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return is_user_manager(request.user)


User = get_user_model()


class CintacUserAdmin(DjangoUserAdmin):
    def _restricted_manager(self, request):
        return not request.user.is_superuser and is_tariff_admin(request.user)

    def _can_manage_user(self, request, obj):
        if not self._restricted_manager(request) or obj is None:
            return True
        return (
            not obj.is_superuser
            and (obj.pk == request.user.pk or not is_tariff_admin(obj))
        )

    def get_fieldsets(self, request, obj=None):
        if self._restricted_manager(request):
            if obj is None:
                return (
                    (None, {"classes": ("wide",), "fields": ("username", "password1", "password2")}),
                    ("Información personal", {"fields": ("first_name", "last_name", "email")}),
                )
            return (
                (None, {"fields": ("username", "password")}),
                ("Información personal", {"fields": ("first_name", "last_name", "email")}),
                ("Estado", {"fields": ("is_active",)}),
            )
        return super().get_fieldsets(request, obj)

    def get_queryset(self, request):
        return super().get_queryset(request)

    def has_module_permission(self, request):
        return is_tariff_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return is_tariff_admin(request.user) and self._can_manage_user(request, obj)

    def has_add_permission(self, request):
        return is_tariff_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return is_tariff_admin(request.user) and self._can_manage_user(request, obj)

    def has_delete_permission(self, request, obj=None):
        if not is_user_manager(request.user):
            return False
        if obj is None:
            return True
        return (
            obj.pk != request.user.pk
            and not obj.is_superuser
            and not is_tariff_admin(obj)
        )


admin.site.unregister(User)
admin.site.register(User, CintacUserAdmin)
