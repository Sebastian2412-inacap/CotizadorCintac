# Utilidades numéricas precisas para convertir unidades y calcular montos.
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


# Endpoints y mensajes para obtener el tipo de cambio de referencia actualizado.
FRANKFURTER_USD_CLP_URL = "https://api.frankfurter.dev/v2/rate/usd/clp"
EXCHANGE_RATE_ERROR = (
    "No se pudo obtener el tipo de cambio actualizado. "
    "Intenta nuevamente más tarde."
)
EXCHANGE_RATE_TIMEOUT_SECONDS = 5

# Capacidad máxima de carga por tamaño de contenedor.
CONTAINER_CAPACITY_TONNES = {
    "20": Decimal("23"),
    "40": Decimal("25"),
}
MAX_WEIGHT_BY_UNIT = {
    "kg": Decimal("220000000"),
    "ton": Decimal("220000"),
}
MAX_WEIGHT_ERROR = (
    "El peso máximo para cotizar es 220.000 toneladas "
    "(220.000.000 kg). Reduce el peso y vuelve a calcular."
)
# Destinos admitidos por el formulario de cotización.
DESTINATIONS = (
    "Valparaíso",
    "San Antonio",
)


def fetch_latest_usd_clp_rate():
    """Obtiene el último tipo USD/CLP publicado por Frankfurter."""
    try:
        with urlopen(
            FRANKFURTER_USD_CLP_URL,
            timeout=EXCHANGE_RATE_TIMEOUT_SECONDS,
        ) as response:
            data = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise ValueError(EXCHANGE_RATE_ERROR) from error

    try:
        if data.get("base") != "USD" or data.get("quote") != "CLP":
            raise ValueError("Par de monedas inesperado.")
        observed_date = date.fromisoformat(data["date"])
        rate = Decimal(str(data["rate"]))
        if not rate.is_finite() or rate <= 0:
            raise ValueError("El tipo de cambio debe ser positivo.")
        rate = rate.quantize(Decimal("0.0001"))
    except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise ValueError(EXCHANGE_RATE_ERROR) from error

    return rate, observed_date


def container_count(weight, unit, container_size="40"):
    # Convierte el dato a Decimal para evitar errores de precisión de float.
    try:
        amount = Decimal(str(weight))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Ingresa un peso válido.") from error

    if not amount.is_finite():
        raise ValueError("Ingresa un peso válido.")
    # Rechaza pesos cero o negativos antes de calcular la carga.
    if amount <= 0:
        raise ValueError("El peso debe ser mayor que cero.")
    if unit not in MAX_WEIGHT_BY_UNIT:
        raise ValueError("Selecciona kg o toneladas.")
    if amount > MAX_WEIGHT_BY_UNIT[unit]:
        raise ValueError(MAX_WEIGHT_ERROR)
    # Normaliza el peso a toneladas según la unidad seleccionada.
    if unit == "kg":
        tonnes = amount / Decimal("1000")
    else:
        tonnes = amount

    if container_size not in CONTAINER_CAPACITY_TONNES:
        raise ValueError("Selecciona un contenedor de 20 o 40 pies.")

    # Redondea hacia arriba para no exceder la capacidad de cada contenedor.
    capacity = CONTAINER_CAPACITY_TONNES[container_size]
    quantity = int((tonnes / capacity).to_integral_value(rounding=ROUND_CEILING))
    return tonnes, quantity


def convert_currency(amount, source, target, clp_per_usd):
    # Conserva la precisión decimal del monto original.
    amount = Decimal(amount)
    # Solo se convierten monedas definidas por la aplicación.
    if source not in {"CLP", "USD"} or target not in {"CLP", "USD"}:
        raise ValueError("La tarifa requiere una moneda definida como CLP o USD antes de convertir.")
    # Evita exigir tipo de cambio cuando las monedas ya coinciden.
    if source == target:
        return amount
    # Comprueba y convierte el tipo de cambio ingresado por el usuario.
    try:
        exchange_rate = Decimal(str(clp_per_usd))
    except InvalidOperation as error:
        raise ValueError("Ingresa un tipo de cambio válido.") from error
    # Un tipo de cambio debe ser un valor positivo.
    if exchange_rate <= 0:
        raise ValueError("Ingresa un tipo de cambio mayor que cero.")
    # Multiplica USD por CLP/USD; en sentido inverso divide CLP por CLP/USD.
    if source == "USD":
        return amount * exchange_rate
    return amount / exchange_rate


def format_amount(amount, currency=None):
    # CLP se expresa en pesos enteros; las demás cantidades conservan dos decimales.
    if currency == "CLP":
        amount = Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        formatted = f"{amount:,.0f}"
    else:
        formatted = f"{Decimal(amount):,.2f}"
    return formatted.translate(str.maketrans({",": ".", ".": ","}))