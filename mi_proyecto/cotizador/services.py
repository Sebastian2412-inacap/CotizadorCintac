# Utilidades numéricas precisas para convertir unidades y calcular montos.
from decimal import Decimal, InvalidOperation, ROUND_CEILING


# Capacidad de carga asumida para calcular la cantidad de contenedores.
CONTAINER_CAPACITY_TONNES = Decimal("25")
# Destinos admitidos por el formulario de cotización.
DESTINATIONS = (
    "Arica",
    "Iquique",
    "Antofagasta",
    "Valparaíso",
    "San Antonio",
    "Talcahuano",
    "Puerto Montt",
    "Punta Arenas",
)


def container_count(weight, unit):
    # Convierte el dato a Decimal para evitar errores de precisión de float.
    try:
        amount = Decimal(str(weight))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Ingresa un peso válido.") from error

    # Rechaza pesos cero o negativos antes de calcular la carga.
    if amount <= 0:
        raise ValueError("El peso debe ser mayor que cero.")
    # Normaliza el peso a toneladas según la unidad seleccionada.
    if unit == "kg":
        tonnes = amount / Decimal("1000")
    elif unit == "ton":
        tonnes = amount
    else:
        raise ValueError("Selecciona kg o toneladas.")

    # Redondea hacia arriba para no exceder la capacidad de cada contenedor.
    quantity = int((tonnes / CONTAINER_CAPACITY_TONNES).to_integral_value(rounding=ROUND_CEILING))
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


def format_amount(amount):
    # Aplica dos decimales y adapta separadores al formato usado en Chile.
    formatted = f"{Decimal(amount):,.2f}"
    return formatted.translate(str.maketrans({",": ".", ".": ","}))