# Herramientas de administración de Django para gestionar las tarifas y rutas.
from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import path, reverse

# Formulario, validación e importación transaccional del Excel de tarifas.
from .excel_import import TariffImportError, import_tariff_workbook
from .forms import TariffExcelUploadForm

# Modelos que se mostrarán en el sitio de administración.
from .models import FreightRate, Route


# Permite editar tarifas relacionadas desde la misma pantalla de una ruta.
class FreightRateInline(admin.TabularInline):
    # Modelo de tarifas subordinadas a la ruta seleccionada.
    model = FreightRate
    # No agrega filas vacías de tarifas automáticamente.
    extra = 0
    # Campos de tarifa visibles en la edición en línea.
    fields = (
        "operation", "destination_port", "carrier", "route_type", "transit_days", "transit_days_max",
        "freight_20", "freight_20_max", "freight_40", "freight_40_max", "currency", "source",
    )


# Registra las rutas y configura cómo se buscan y editan en el admin.
@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
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
class FreightRateAdmin(admin.ModelAdmin):
    change_list_template = "admin/cotizador/freightrate/change_list.html"

    # Columnas útiles para revisar montos, rangos y actualización.
    list_display = (
        "operation", "route", "destination_port", "carrier", "transit_days", "transit_days_max",
        "freight_20", "freight_20_max", "freight_40", "freight_40_max", "currency", "source", "updated_at",
    )
    # Filtros para acotar tarifas por moneda, país, destino o tipo de ruta.
    list_filter = ("operation", "currency", "route__country", "destination_port", "route_type")
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
        if not (self.has_add_permission(request) and self.has_change_permission(request)):
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
                    if result.export_rows == 0:
                        summary += " La hoja Exportaciones está vacía; no se borró ni modificó ninguna tarifa."
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
