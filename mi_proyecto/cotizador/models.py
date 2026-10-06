# Componentes del ORM de Django para definir tablas y restricciones.
from django.db import models


# País y puerto de origen que identifican una ruta de transporte.
class Route(models.Model):
    # País en el que se encuentra el puerto de salida.
    country = models.CharField(max_length=80)
    # Nombre del puerto de origen de la ruta.
    origin_port = models.CharField(max_length=120)

    class Meta:
        # Orden predeterminado para mostrar rutas por país y puerto.
        ordering = ["country", "origin_port"]
        # Impide registrar dos veces el mismo puerto de origen en un país.
        constraints = [
            models.UniqueConstraint(
                fields=["country", "origin_port"],
                name="unique_origin_country_port",
            )
        ]

    def __str__(self):
        # Representación legible de una ruta en el administrador y formularios.
        return f"{self.origin_port}, {self.country}"


# Valores de flete, tránsito y referencia asociados a una ruta.
class FreightRate(models.Model):
    OPERATION_CHOICES = [
        ("import", "Importación"),
        ("export", "Exportación"),
    ]

    # Monedas permitidas para almacenar y presentar los montos.
    CURRENCY_CHOICES = [
        ("CLP", "CLP"),
        ("USD", "USD"),
    ]

    # Ruta de origen; al eliminarla también se eliminan sus tarifas.
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="rates")
    # Sentido comercial de la tarifa.
    operation = models.CharField(max_length=6, choices=OPERATION_CHOICES, default="import")
    # Puerto de destino; puede estar vacío para tarifas históricas generales.
    destination_port = models.CharField(max_length=120, blank=True)
    # Nombre del transportista o embarcador, cuando se conoce.
    carrier = models.CharField(max_length=120, blank=True)
    # Modalidad o descripción del recorrido.
    route_type = models.CharField(max_length=80, blank=True)
    # Referencia documental desde la que se obtuvo la tarifa.
    source = models.CharField(max_length=200, blank=True)
    # Tiempo mínimo/base de tránsito expresado en días.
    transit_days = models.PositiveIntegerField()
    # Límite superior opcional del rango de tránsito.
    transit_days_max = models.PositiveIntegerField(null=True, blank=True)
    # Tarifa mínima/base para contenedor de 20 pies.
    freight_20 = models.DecimalField(max_digits=14, decimal_places=2)
    # Límite superior opcional de la tarifa para 20 pies.
    freight_20_max = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    # Tarifa mínima/base para contenedor de 40 pies.
    freight_40 = models.DecimalField(max_digits=14, decimal_places=2)
    # Límite superior opcional de la tarifa para 40 pies.
    freight_40_max = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    # Moneda asociada a los valores de flete.
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="USD")
    # Fecha y hora que Django actualiza al guardar el registro.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Ordena tarifas por ruta, destino y transportista.
        ordering = ["route__country", "route__origin_port", "destination_port", "carrier"]
        # Evita duplicados y asegura valores no negativos y rangos coherentes.
        constraints = [
            models.UniqueConstraint(
                fields=["route", "operation", "destination_port", "carrier"],
                name="unique_route_destination_carrier",
            ),
            models.CheckConstraint(condition=models.Q(freight_20__gte=0), name="freight_20_non_negative"),
            models.CheckConstraint(condition=models.Q(freight_40__gte=0), name="freight_40_non_negative"),
            models.CheckConstraint(
                condition=models.Q(freight_20_max__isnull=True) | models.Q(freight_20_max__gte=models.F("freight_20")),
                name="freight_20_max_gte_min",
            ),
            models.CheckConstraint(
                condition=models.Q(freight_40_max__isnull=True) | models.Q(freight_40_max__gte=models.F("freight_40")),
                name="freight_40_max_gte_min",
            ),
            models.CheckConstraint(
                condition=models.Q(transit_days_max__isnull=True) | models.Q(transit_days_max__gte=models.F("transit_days")),
                name="transit_days_max_gte_min",
            ),
        ]

    @property
    def has_range(self):
        # Informa si se indicó al menos un límite superior de precio.
        return self.freight_20_max is not None or self.freight_40_max is not None

    def __str__(self):
        # Añade destino y transportista solo cuando están informados.
        destination = f" → {self.destination_port}" if self.destination_port else ""
        carrier = f" · {self.carrier}" if self.carrier else ""
        return f"{self.route}{destination}{carrier}"
