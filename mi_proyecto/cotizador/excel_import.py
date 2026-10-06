import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

from django.db import transaction
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from .models import FreightRate, Route


EXPECTED_HEADERS = (
    "pais",
    "tipotransporte",
    "puertospaisorigen",
    "diastransito",
    "cantidadcont20",
    "fletetotal20",
    "cantidadcont40",
    "fletetotal40",
)
COUNTRIES = {
    "china": "China",
    "japon": "Japón",
    "espana": "España",
    "eeuu": "EE.UU.",
    "peru": "Perú",
}
CENT = Decimal("0.01")
MAX_RATE_AMOUNT = Decimal("999999999999.99")


class TariffImportError(ValueError):
    pass


@dataclass(frozen=True)
class ExcelTariff:
    country: str
    origin_port: str
    transit_days: int
    freight_20: Decimal
    freight_40: Decimal
    worksheet_row: int


@dataclass(frozen=True)
class ImportResult:
    created: int
    updated: int
    export_rows: int


def _normalized(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _cell_text(value, label, row_number):
    if not isinstance(value, str) or not value.strip():
        raise TariffImportError(f"Fila {row_number}: falta el valor de {label}.")
    return value.strip()


def _decimal(value, label, row_number):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TariffImportError(f"Fila {row_number}: {label} debe ser un valor numérico guardado en Excel.")
    try:
        amount = Decimal(str(value))
        rounded_amount = amount.quantize(CENT)
    except (InvalidOperation, ValueError) as error:
        raise TariffImportError(f"Fila {row_number}: {label} no es un número válido.") from error
    if (
        not amount.is_finite()
        or amount < 0
        or rounded_amount != amount
        or rounded_amount > MAX_RATE_AMOUNT
    ):
        raise TariffImportError(f"Fila {row_number}: {label} debe ser un monto no negativo con hasta 2 decimales.")
    return rounded_amount


def _country_rates(sheet):
    rates = {}
    for row_number in range(1, sheet.max_row + 1):
        label = sheet.cell(row_number, 10).value
        if not isinstance(label, str):
            continue
        match = re.fullmatch(
            r"valorcontenedorde(.+?)1de(20|40)",
            _normalized(label),
        )
        if not match:
            continue
        raw_country, size = match.groups()
        country = COUNTRIES.get(raw_country)
        if country is None:
            raise TariffImportError(
                f"Fila {row_number}: el cuadro de valores contiene un país no reconocido: {raw_country}."
            )
        amount = _decimal(sheet.cell(row_number, 11).value, f"valor contenedor {size}' de {country}", row_number)
        rates.setdefault(country, {})[size] = amount

    for country in COUNTRIES.values():
        if set(rates.get(country, {})) != {"20", "40"}:
            raise TariffImportError(
                f"Falta el valor unitario de contenedor de 20 y/o 40 pies para {country} en las columnas J:K."
            )
    return rates


def _read_export_rows(sheet):
    populated_rows = []
    for row_number, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if any(value not in (None, "") for value in row):
            populated_rows.append(row_number)
    if populated_rows:
        rows = ", ".join(map(str, populated_rows[:10]))
        raise TariffImportError(
            "La hoja Exportaciones contiene datos (filas "
            f"{rows}); esta carga solo procesa importaciones marítimas. No se modificó la base de datos."
        )
    return 0


def read_tariff_workbook(uploaded_file):
    filename = PurePosixPath(uploaded_file.name.replace("\\", "/")).name
    try:
        workbook = load_workbook(uploaded_file, read_only=True, data_only=True)
    except (InvalidFileException, OSError, ValueError, KeyError) as error:
        raise TariffImportError("No se pudo leer el archivo. Verifica que sea un Excel .xlsx válido.") from error

    try:
        if "Importaciones" not in workbook.sheetnames:
            raise TariffImportError("El libro debe incluir una hoja llamada Importaciones.")
        if "Exportaciones" not in workbook.sheetnames:
            raise TariffImportError("El libro debe incluir una hoja llamada Exportaciones.")

        import_sheet = workbook["Importaciones"]
        headers = tuple(_normalized(import_sheet.cell(1, column).value) for column in range(1, 9))
        if headers != EXPECTED_HEADERS:
            raise TariffImportError(
                "Los encabezados A:H de Importaciones no coinciden con el formato esperado "
                "(país, transporte, puerto, tránsito, cantidades y fletes de 20'/40')."
            )

        country_rates = _country_rates(import_sheet)
        tariffs = []
        seen_routes = set()
        for row_number in range(2, import_sheet.max_row + 1):
            values = [import_sheet.cell(row_number, column).value for column in range(1, 9)]
            if all(value in (None, "") for value in values):
                continue
            if any(value in (None, "") for value in values):
                raise TariffImportError(f"Fila {row_number}: hay campos incompletos en las columnas A:H.")

            raw_country = _cell_text(values[0], "país", row_number)
            country = COUNTRIES.get(_normalized(raw_country))
            if country is None:
                raise TariffImportError(f"Fila {row_number}: país no reconocido: {raw_country}.")
            transport = _normalized(_cell_text(values[1], "tipo de transporte", row_number))
            if transport != "maritimo":
                raise TariffImportError(
                    f"Fila {row_number}: solo se pueden importar tarifas marítimas; se encontró {values[1]!r}."
                )
            origin_port = _cell_text(values[2], "puerto de origen", row_number)
            if len(origin_port) > 120:
                raise TariffImportError(
                    f"Fila {row_number}: el puerto de origen no puede superar 120 caracteres."
                )
            route_key = (country, _normalized(origin_port))
            if route_key in seen_routes:
                raise TariffImportError(
                    f"Fila {row_number}: la ruta {origin_port}, {country} está repetida en el libro."
                )
            seen_routes.add(route_key)

            transit_text = _normalized(_cell_text(values[3], "días de tránsito", row_number))
            transit_match = re.fullmatch(r"(\d+)dias?", transit_text)
            if transit_match is None:
                raise TariffImportError(
                    f"Fila {row_number}: el tránsito debe expresarse como un número seguido de 'días'."
                )
            transit_days = int(transit_match.group(1))
            if transit_days <= 0:
                raise TariffImportError(f"Fila {row_number}: los días de tránsito deben ser mayores que cero.")

            counts = []
            for value, size in ((values[4], "20"), (values[6], "40")):
                count = _decimal(value, f"cantidad de contenedores de {size} pies", row_number)
                if count <= 0 or count != count.to_integral_value():
                    raise TariffImportError(
                        f"Fila {row_number}: la cantidad de contenedores de {size} pies debe ser un entero positivo."
                    )
                counts.append(int(count))

            totals = [
                _decimal(values[5], "flete total 20'", row_number),
                _decimal(values[7], "flete total 40'", row_number),
            ]
            unit_rates = country_rates[country]
            for total, count, size in zip(totals, counts, ("20", "40")):
                if total != unit_rates[size] * count:
                    raise TariffImportError(
                        f"Fila {row_number}: el flete total de {size}' ({total}) no coincide con "
                        f"{count} × el valor unitario guardado en J:K ({unit_rates[size]}). "
                        "Recalcula y guarda el Excel antes de volver a cargarlo."
                    )

            tariffs.append(
                ExcelTariff(
                    country=country,
                    origin_port=origin_port,
                    transit_days=transit_days,
                    freight_20=unit_rates["20"],
                    freight_40=unit_rates["40"],
                    worksheet_row=row_number,
                )
            )

        if not tariffs:
            raise TariffImportError("No se encontraron tarifas en la hoja Importaciones.")
        export_rows = _read_export_rows(workbook["Exportaciones"])
        return filename, tariffs, export_rows
    finally:
        workbook.close()


@transaction.atomic
def import_tariff_workbook(uploaded_file):
    filename, tariffs, export_rows = read_tariff_workbook(uploaded_file)
    created = 0
    updated = 0
    for tariff in tariffs:
        route, _ = Route.objects.get_or_create(
            country=tariff.country,
            origin_port=tariff.origin_port,
        )
        _, was_created = FreightRate.objects.update_or_create(
            route=route,
            operation="import",
            destination_port="",
            carrier="",
            defaults={
                "route_type": "Marítimo",
                "source": f"{filename} · Importaciones!A{tariff.worksheet_row}:H{tariff.worksheet_row}",
                "transit_days": tariff.transit_days,
                "transit_days_max": None,
                "freight_20": tariff.freight_20,
                "freight_20_max": None,
                "freight_40": tariff.freight_40,
                "freight_40_max": None,
                "currency": "USD",
            },
        )
        created += was_created
        updated += not was_created

    return ImportResult(created=created, updated=updated, export_rows=export_rows)
