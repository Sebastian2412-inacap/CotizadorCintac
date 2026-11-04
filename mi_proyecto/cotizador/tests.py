# Valores decimales y utilidades de prueba de Django.
from io import BytesIO
import json
from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import Workbook, load_workbook
from PIL import Image

# Modelo y servicios cuyo comportamiento se valida.
from .forms import FreightRateEntryForm, ImportRouteAdminForm
from .models import FreightRate, QuoteHistory, Route, UserProfile
from .services import (
    DESTINATIONS,
    EXCHANGE_RATE_ERROR,
    container_count,
    convert_currency,
    fetch_latest_usd_clp_rate,
    format_amount,
)


# Pruebas aisladas de cálculos que no necesitan acceso a la base de datos.
class CalculationTests(SimpleTestCase):
    def test_container_capacity_rounds_up_by_container_size(self):
        # Comprueba ambos límites de carga y la conversión de kilogramos.
        self.assertEqual(container_count("23", "ton", "20"), (Decimal("23"), 1))
        self.assertEqual(container_count("23.1", "ton", "20"), (Decimal("23.1"), 2))
        self.assertEqual(container_count("25", "ton", "40"), (Decimal("25"), 1))
        self.assertEqual(container_count("26", "ton", "40"), (Decimal("26"), 2))
        self.assertEqual(container_count("26000", "kg", "40"), (Decimal("26"), 2))

    def test_container_count_accepts_the_maximum_weight_in_each_unit(self):
        self.assertEqual(
            container_count("220000", "ton", "40"),
            (Decimal("220000"), 8800),
        )
        self.assertEqual(
            container_count("220000000", "kg", "40"),
            (Decimal("220000"), 8800),
        )

    def test_container_count_rejects_weights_above_the_maximum(self):
        for weight, unit in (("220000.01", "ton"), ("220000000.01", "kg")):
            with self.subTest(unit=unit):
                with self.assertRaisesMessage(ValueError, "220.000 toneladas"):
                    container_count(weight, unit)

    def test_currency_conversion_uses_the_provided_reference_rate(self):
        # Verifica conversiones en ambos sentidos y moneda de destino idéntica.
        self.assertEqual(convert_currency("100", "USD", "CLP", "900"), Decimal("90000"))
        self.assertEqual(convert_currency("90000", "CLP", "USD", "900"), Decimal("100"))
        self.assertEqual(convert_currency("100", "USD", "USD", ""), Decimal("100"))

    def test_currency_amount_format_uses_integer_pesos_and_decimal_dollars(self):
        self.assertEqual(format_amount("1628236.5", "CLP"), "1.628.237")
        self.assertEqual(format_amount("2812408.4", "CLP"), "2.812.408")
        self.assertEqual(format_amount("1650", "USD"), "1.650,00")

    def test_fetch_latest_usd_clp_rate_uses_frankfurter_pair(self):
        response = BytesIO(
            json.dumps(
                {"date": "2026-10-29", "base": "USD", "quote": "CLP", "rate": 986.81}
            ).encode()
        )
        with patch("cotizador.services.urlopen", return_value=response) as urlopen_mock:
            rate, observed_date = fetch_latest_usd_clp_rate()

        self.assertEqual(rate, Decimal("986.8100"))
        self.assertEqual(observed_date, date(2026, 10, 29))
        urlopen_mock.assert_called_once_with(
            "https://api.frankfurter.dev/v2/rate/usd/clp",
            timeout=5,
        )

    def test_fetch_latest_usd_clp_rate_rejects_an_invalid_response(self):
        response = BytesIO(
            json.dumps(
                {"date": "2026-10-29", "base": "EUR", "quote": "CLP", "rate": 1000}
            ).encode()
        )
        with patch("cotizador.services.urlopen", return_value=response):
            with self.assertRaisesMessage(ValueError, EXCHANGE_RATE_ERROR):
                fetch_latest_usd_clp_rate()

    def test_chilean_destinations_are_available(self):
        # El cotizador admite únicamente los dos puertos de importación definidos.
        self.assertEqual(DESTINATIONS, ("Valparaíso", "San Antonio"))
        self.assertIn("San Antonio", DESTINATIONS)
        self.assertIn("Valparaíso", DESTINATIONS)


# Pruebas de la vista con base de datos temporal y cliente HTTP de Django.
class QuoteViewTests(TestCase):
    def setUp(self):
        # Autentica los escenarios funcionales de cotización.
        self.user = get_user_model().objects.create_user(
            username="cotizador",
            password="Clave-segura-123",
        )
        self.client.force_login(self.user)
        exchange_rate_patcher = patch(
            "cotizador.views.fetch_latest_usd_clp_rate",
            return_value=(Decimal("900.0000"), date(2026, 10, 29)),
        )
        self.exchange_rate_api = exchange_rate_patcher.start()
        self.addCleanup(exchange_rate_patcher.stop)

        # Recupera la tarifa histórica y una tarifa referencial de ejemplo.
        self.legacy_rate = FreightRate.objects.get(
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
            carrier="",
        )
        self.reference_rate = FreightRate.objects.get(
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="San Antonio",
            carrier="",
        )

    def payload(self, rate=None, **overrides):
        # Construye un POST válido y permite cambiar campos para cada escenario.
        rate = rate or self.legacy_rate
        data = {
            "operation": "import",
            "transport": "sea",
            "rate_id": rate.pk,
            "destination": "San Antonio",
            "weight": "26000",
            "weight_unit": "kg",
            "margin_days": "3",
            "source_currency": rate.currency,
            "target_currency": "",
            "exchange_rate": "900",
        }
        data.update(overrides)
        return data

    def test_anonymous_users_are_redirected_to_login(self):
        # Exige autenticación antes de mostrar o procesar cotizaciones.
        self.client.logout()
        response = self.client.get("/")
        self.assertRedirects(response, f"{reverse('login')}?next=/")
        self.assertIn("no-store", response["Cache-Control"])

    def test_authenticated_pages_are_not_cached_by_the_browser(self):
        for url in (reverse("quote"), reverse("rates"), reverse("quote_history"), reverse("user_profile")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertContains(response, 'class="rail-toggle" type="button" aria-controls="primary-navigation" aria-expanded="true"')
                self.assertContains(response, 'aria-label="Ocultar menú"')
                self.assertContains(response, 'id="primary-navigation"')
                self.assertContains(response, 'cotizador/navigation.js')
                self.assertContains(response, 'class="topbar-brand"')
                self.assertContains(response, 'class="theme-toggle"')
                self.assertContains(response, 'aria-label="Activar modo oscuro"')
                self.assertContains(response, 'cotizador/theme.js')
                self.assertContains(response, reverse("user_profile"))

    def test_quote_page_exposes_currency_conversion_and_history_navigation(self):
        response = self.client.get(reverse("quote"))

        self.assertContains(response, "Importación marítima")
        self.assertNotContains(response, "Exportación")
        self.assertNotContains(response, "Aéreo")
        self.assertNotContains(response, "Arica")
        self.assertContains(response, 'details class="currency-details" open')
        self.assertContains(response, "CLP ↔ USD")
        self.assertContains(response, "Moneda desde la que convertir")
        self.assertContains(response, "Peso chileno (CLP)")
        self.assertContains(response, "Dólar estadounidense (USD)")
        self.assertNotContains(response, 'id="exchange_rate"')
        self.assertContains(response, "se consultará automáticamente")
        self.assertContains(response, 'max="220000000"')
        self.assertContains(response, "Peso máximo para cotizar: 220.000 toneladas (220.000.000 kg).")
        self.assertNotContains(response, 'id="container_size"')
        self.assertContains(response, f'href="{reverse("quote_history")}"')

    def test_quote_rejects_weight_above_maximum_and_suggests_the_limit(self):
        for weight, unit in (("220000.01", "ton"), ("220000000.01", "kg")):
            with self.subTest(unit=unit):
                response = self.client.post(
                    "/",
                    self.payload(weight=weight, weight_unit=unit),
                )
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.context["result"])
                self.assertContains(response, "El peso máximo para cotizar es 220.000 toneladas")
                self.assertContains(response, "Reduce el peso y vuelve a calcular.")

    def test_login_page_accepts_registered_users(self):
        # Verifica el formulario y el retorno al recurso que pidió el usuario.
        self.client.logout()
        response = self.client.post(
            reverse("login"),
            {"username": "cotizador", "password": "Clave-segura-123", "next": "/"},
        )
        self.assertRedirects(response, "/")
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_login_page_uses_the_new_responsive_layout(self):
        self.client.logout()

        response = self.client.get(reverse("login"))

        self.assertContains(response, 'class="login-layout"')
        self.assertContains(response, "PLATAFORMA DE COMERCIO EXTERIOR")
        self.assertContains(response, "Acceso privado para usuarios registrados")

    def test_login_page_rejects_invalid_credentials(self):
        # No permite el acceso con una combinación incorrecta.
        self.client.logout()
        response = self.client.post(
            reverse("login"),
            {"username": "cotizador", "password": "incorrecta"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "El usuario o la contraseña no son correctos.")

    def test_login_is_locked_for_ten_seconds_after_three_failed_attempts(self):
        self.client.logout()
        login_url = reverse("login")
        invalid_credentials = {"username": "cotizador", "password": "incorrecta"}

        for _ in range(3):
            response = self.client.post(login_url, invalid_credentials)
            self.assertEqual(response.status_code, 200)

        self.assertContains(response, "Espera 10 segundos")
        self.assertContains(response, 'id="login-countdown"')
        self.assertGreater(response.context["login_wait_seconds"], 0)

        response = self.client.post(
            login_url,
            {"username": "cotizador", "password": "Clave-segura-123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertContains(response, "Se alcanzó el límite de intentos")

        session = self.client.session
        session["cintac_login_locked_until"] = 1
        session.save()
        response = self.client.post(
            login_url,
            {"username": "cotizador", "password": "Clave-segura-123"},
        )
        self.assertRedirects(response, "/")
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_logout_requires_post_and_ends_session(self):
        # El cierre de sesión usa POST y revoca la sesión autenticada.
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("_auth_user_id", self.client.session)
        back_response = self.client.get(reverse("quote"))
        self.assertRedirects(back_response, f"{reverse('login')}?next=/")
        self.assertIn("no-store", back_response["Cache-Control"])

    def test_initial_report_rates_are_now_usd(self):
        # Confirma moneda y monto iniciales de las tarifas históricas.
        self.assertEqual(self.legacy_rate.currency, "USD")
        self.assertEqual(self.legacy_rate.freight_20, Decimal("4300.00"))

    def test_reference_rates_are_seeded_as_ranges(self):
        # Comprueba que las referencias tengan moneda, rangos, tránsito y fuente.
        self.assertEqual(self.reference_rate.currency, "USD")
        self.assertEqual(self.reference_rate.freight_20, Decimal("1600.00"))
        self.assertEqual(self.reference_rate.freight_20_max, Decimal("2800.00"))
        self.assertEqual(self.reference_rate.transit_days, 25)
        self.assertEqual(self.reference_rate.transit_days_max, 32)
        self.assertEqual(self.reference_rate.source, "Segucargo / Delpa Group 2026")

    def test_usd_tariff_quote_displays_clp_equivalent_and_original_usd(self):
        # Verifica conversión automática, monto original, contenedores y tránsito.
        response = self.client.post("/", self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 contenedores")
        self.assertContains(response, "Comparativa de contenedores")
        self.assertContains(response, "20 pies")
        self.assertContains(response, "40 pies")
        self.assertContains(response, "7.740.000")
        self.assertContains(response, "Base: USD 8.600,00")
        self.assertContains(response, "USD 8.600,00")
        self.assertContains(response, "48 días")
        self.assertContains(response, "MENOR PRESUPUESTO ESTIMADO")
        self.assertContains(response, "San Antonio")

    def test_reference_quote_displays_price_and_transit_ranges(self):
        # Comprueba la presentación de rangos de flete y días de tránsito.
        response = self.client.post("/", self.payload(rate=self.reference_rate))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2.880.000 – 5.040.000")
        self.assertContains(response, "USD 3.200,00 – 5.600,00")
        self.assertContains(response, "25–32 días")
        self.assertContains(response, "28–35 días")
        self.assertContains(response, "Segucargo / Delpa Group 2026")
        options = response.context["result"]["container_options"]
        self.assertEqual(options[0]["amount"], "2.880.000")
        self.assertEqual(options[0]["amount_max"], "5.040.000")
        self.assertEqual(options[1]["amount"], "4.140.000")
        self.assertEqual(options[1]["amount_max"], "6.840.000")

    def test_clp_results_round_to_integer_without_changing_usd_decimals(self):
        self.reference_rate.freight_20 = Decimal("1650")
        self.reference_rate.freight_20_max = Decimal("2850")
        self.reference_rate.save()
        with patch(
            "cotizador.views.fetch_latest_usd_clp_rate",
            return_value=(Decimal("986.8100"), date(2026, 10, 29)),
        ):
            response = self.client.post(
                "/",
                self.payload(rate=self.reference_rate, weight="23000"),
            )

        result = response.context["result"]
        self.assertEqual(result["amount"], "1.628.237")
        self.assertEqual(result["amount_max"], "2.812.409")
        self.assertContains(response, "CLP 1.628.237")
        self.assertContains(response, "Base: USD 1.650,00 – 2.850,00")
        self.assertNotContains(response, "1.628.236,50")

        history_response = self.client.get(reverse("quote_history"))
        self.assertContains(history_response, "CLP 1.628.237")
        self.assertContains(history_response, "Base seleccionada: USD 1.650,00")

        with patch(
            "cotizador.views.fetch_latest_usd_clp_rate",
            return_value=(Decimal("986.8100"), date(2026, 10, 29)),
        ):
            excel_response = self.client.post(
                "/",
                self.payload(rate=self.reference_rate, weight="23000", export_excel="1"),
            )
        workbook = load_workbook(BytesIO(excel_response.content), data_only=True)
        sheet = workbook["Cotización"]
        rows = {
            row[0].value: (row[1].value, row[2].value if len(row) > 2 else None)
            for row in sheet.iter_rows(min_row=1, max_col=3)
            if row[0].value
        }
        self.assertEqual(rows["Flete total mínimo"], ("1.628.237", "CLP"))
        self.assertEqual(rows["Monto base mínimo"], ("1.650,00", "USD"))

    def test_quote_recommends_the_cheapest_feasible_container_size(self):
        self.legacy_rate.freight_20 = Decimal("1000")
        self.legacy_rate.freight_40 = Decimal("1500")
        self.legacy_rate.save()

        response = self.client.post(
            "/",
            self.payload(weight="24000"),
        )

        options = response.context["result"]["container_options"]
        self.assertEqual([option["quantity"] for option in options], [2, 1])
        self.assertEqual(response.context["result"]["recommendation"]["size"], "40")
        self.assertEqual(response.context["result"]["recommendation"]["quantity"], 1)
        self.assertContains(response, "Cantidad necesaria para 24,00 TN")
        self.assertContains(response, "2 contenedores")
        self.assertContains(response, "1 contenedor")
        self.assertContains(response, "Tarifa por unidad")
        self.assertContains(response, "Total estimado")
        self.assertContains(response, "Menor costo")

        self.legacy_rate.freight_40 = Decimal("2500")
        self.legacy_rate.save()
        response = self.client.post(
            "/",
            self.payload(weight="24000"),
        )
        self.assertEqual(response.context["result"]["recommendation"]["size"], "20")
        self.assertEqual(response.context["result"]["recommendation"]["quantity"], 2)

    def test_valid_quote_can_be_downloaded_as_excel(self):
        response = self.client.post("/", self.payload(export_excel="1"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("attachment; filename=", response["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        sheet = workbook["Cotización"]
        rows = {
            row[0].value: (row[1].value, row[2].value if len(row) > 2 else None)
            for row in sheet.iter_rows(min_row=1, max_col=3)
            if row[0].value
        }
        self.assertEqual(rows["Flete total mínimo"], ("7.740.000", "CLP"))
        self.assertEqual(rows["Monto base mínimo"], ("8.600,00", "USD"))
        self.assertEqual(rows["Tarifa registrada mínimo"], ("8.600,00", "USD"))
        self.assertEqual(rows["Tipo de cambio aplicado"], ("900.0000", "CLP por USD"))
        self.assertEqual(rows["Fecha del tipo de cambio"][0].date(), date(2026, 10, 29))
        self.assertEqual(rows["Cantidad de contenedores"][0], 2)
        self.assertEqual(rows["Destino"][0], "San Antonio")
        self.assertIn("Recomendación económica", rows)
        self.assertIn("Comparación de alternativas de embarcador", rows)
        comparison_rows = list(sheet.iter_rows(values_only=True))
        self.assertIn(("20 pies", 2, "23 TN", "8.600,00", "Sin máximo", "USD", "7.740.000", "Sin máximo", "CLP"), [row[:9] for row in comparison_rows])
        self.assertIn(("40 pies", 2, "25 TN", "11.400,00", "Sin máximo", "USD", "10.260.000", "Sin máximo", "CLP"), [row[:9] for row in comparison_rows])

    def test_excel_includes_both_container_options_and_their_price_ranges(self):
        response = self.client.post(
            "/",
            self.payload(rate=self.reference_rate, export_excel="1"),
        )
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        sheet = workbook["Cotización"]
        comparison_rows = list(sheet.iter_rows(values_only=True))

        self.assertIn(
            ("20 pies", 2, "23 TN", "3.200,00", "5.600,00", "USD", "2.880.000", "5.040.000", "CLP"),
            [row[:9] for row in comparison_rows],
        )
        self.assertIn(
            ("40 pies", 2, "25 TN", "4.600,00", "7.600,00", "USD", "4.140.000", "6.840.000", "CLP"),
            [row[:9] for row in comparison_rows],
        )
        alternative = next(row for row in comparison_rows if row[0] == "Sin especificar" and row[7] == "CLP")
        self.assertEqual(
            tuple(alternative[:11]),
            (
                "Sin especificar",
                "4.300,00",
                "Sin máximo",
                "USD",
                2,
                "7.740.000",
                "Sin máximo",
                "CLP",
                48,
                "Sin máximo",
                "Sin especificar",
            ),
        )

    def test_reference_rate_forces_its_validated_destination(self):
        # Evita que el selector contradiga el destino asociado a la tarifa.
        response = self.client.post(
            "/",
            self.payload(rate=self.reference_rate, destination="Valparaíso"),
        )
        self.assertEqual(response.context["result"]["destination"], "San Antonio")
        self.assertEqual(response.context["form"]["destination"], "San Antonio")

    def test_air_quote_is_not_calculated_without_rates(self):
        # Rechaza una modalidad aérea aunque se intente enviar manualmente.
        response = self.client.post("/", self.payload(transport="air"))
        self.assertContains(response, "El cotizador solo permite transporte marítimo")
        self.assertNotContains(response, "2 contenedores")

    def test_quote_rejects_destinations_outside_import_ports(self):
        response = self.client.post("/", self.payload(destination="Iquique"))

        self.assertContains(response, "Selecciona uno de los destinos predefinidos")
        self.assertNotContains(response, "2 contenedores")

    def test_usd_rate_uses_the_latest_api_rate_instead_of_a_posted_rate(self):
        # La cotización debe ignorar el valor manual y usar la tasa consultada.
        response = self.client.post(
            "/",
            self.payload(exchange_rate="1"),
        )
        self.assertContains(response, "7.740.000")
        self.assertContains(response, "MENOR PRESUPUESTO ESTIMADO")
        self.assertContains(response, "publicado el 29/10/2026")
        saved_quote = QuoteHistory.objects.get(user=self.user)
        self.assertEqual(saved_quote.source_currency, "USD")
        self.assertEqual(saved_quote.currency, "CLP")
        self.assertEqual(saved_quote.exchange_rate, Decimal("900"))
        self.assertEqual(saved_quote.amount, Decimal("7740000"))
        self.exchange_rate_api.assert_called_once_with()

    def test_selected_usd_converts_a_clp_tariff_to_clp(self):
        self.legacy_rate.currency = "CLP"
        self.legacy_rate.freight_20 = Decimal("4000000")
        self.legacy_rate.freight_40 = Decimal("5000000")
        self.legacy_rate.save()

        response = self.client.post(
            "/",
            self.payload(source_currency="USD", exchange_rate="1000"),
        )

        self.assertContains(response, "8.000.000")
        self.assertContains(response, "MENOR PRESUPUESTO ESTIMADO")
        saved_quote = QuoteHistory.objects.get(user=self.user)
        self.assertEqual(saved_quote.source_currency, "USD")
        self.assertEqual(saved_quote.currency, "CLP")
        self.assertEqual(saved_quote.source_amount, Decimal("8888.89"))
        self.assertEqual(saved_quote.amount, Decimal("8000000"))

    def test_selected_clp_converts_a_usd_tariff_to_usd(self):
        response = self.client.post(
            "/",
            self.payload(source_currency="CLP", exchange_rate="900"),
        )

        self.assertContains(response, "8.600,00")
        self.assertContains(response, "MENOR PRESUPUESTO ESTIMADO")
        saved_quote = QuoteHistory.objects.get(user=self.user)
        self.assertEqual(saved_quote.source_currency, "CLP")
        self.assertEqual(saved_quote.currency, "USD")
        self.assertEqual(saved_quote.source_amount, Decimal("7740000"))
        self.assertEqual(saved_quote.rate_currency, "USD")
        self.assertEqual(saved_quote.amount, Decimal("8600"))

    def test_unavailable_exchange_rate_does_not_save_a_quote(self):
        with patch(
            "cotizador.views.fetch_latest_usd_clp_rate",
            side_effect=ValueError(EXCHANGE_RATE_ERROR),
        ):
            response = self.client.post("/", self.payload())

        self.assertContains(response, EXCHANGE_RATE_ERROR)
        self.assertFalse(QuoteHistory.objects.exists())

    def test_quote_history_lists_saved_quotes_only_for_the_current_user(self):
        self.client.post("/", self.payload())
        other_user = get_user_model().objects.create_user(
            username="otro-cotizador",
            password="Clave-segura-456",
        )

        response = self.client.get(reverse("quote_history"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shanghai")
        self.assertContains(response, "7.740.000")
        self.assertContains(response, "Base seleccionada: USD 8.600,00")
        self.assertContains(response, reverse("quote_history_detail", args=(QuoteHistory.objects.get(user=self.user).pk,)))
        self.assertNotContains(response, "Eliminar todo el historial")
        self.assertNotContains(response, '<dialog class="history-clear-dialog" id="clear-history-dialog"')
        self.assertContains(response, 'cotizador/clear_history.js')
        self.assertEqual(response.context["total_quotes"], 1)
        self.assertEqual(QuoteHistory.objects.filter(user=other_user).count(), 0)

    def test_quote_history_lists_quotes_from_all_users_with_author_names(self):
        self.client.post("/", self.payload())
        other_user = get_user_model().objects.create_user(
            username="otro-cotizador",
            first_name="Otra",
            last_name="Persona",
        )
        self.client.force_login(other_user)
        self.client.post("/", self.payload())
        self.client.force_login(self.user)
        manager_group = Group.objects.get(name="Administración CINTAC")
        manager_group.user_set.add(self.user)
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        response = self.client.get(reverse("quote_history"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_quotes"], 2)
        self.assertContains(response, "cotizador")
        self.assertContains(response, "Otra Persona")
        self.assertContains(response, "Administrar historial")
        self.assertEqual(QuoteHistory.objects.filter(user=other_user).count(), 1)

    def test_quote_history_detail_shows_saved_calculation_and_comparisons(self):
        alternative = FreightRate.objects.create(
            route=self.legacy_rate.route,
            destination_port="",
            carrier="Embarcador guardado",
            transit_days=43,
            freight_20=Decimal("4200"),
            freight_20_max=Decimal("4700"),
            freight_40=Decimal("5600"),
            currency="USD",
            source="Tarifa alternativa de prueba",
        )
        self.client.post("/", self.payload())
        saved_quote = QuoteHistory.objects.get(user=self.user)
        alternative.delete()
        self.legacy_rate.delete()

        response = self.client.get(
            reverse("quote_history_detail", args=(saved_quote.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Comparativa de contenedores")
        self.assertContains(response, "Contenedor de 20 pies")
        self.assertContains(response, "Contenedor de 40 pies")
        self.assertContains(response, "MENOR PRESUPUESTO ESTIMADO")
        self.assertContains(response, "Peso informado")
        self.assertContains(response, "Embarcador guardado")
        self.assertContains(response, "Tarifa alternativa de prueba")
        self.assertContains(response, "7.560.000")
        self.assertTrue(response.context["details"]["is_complete_snapshot"])
        self.assertContains(
            response,
            reverse("quote_history_excel", args=(saved_quote.pk,)),
        )

    def test_quote_history_excel_exports_the_selected_saved_quote(self):
        alternative = FreightRate.objects.create(
            route=self.legacy_rate.route,
            destination_port="",
            carrier="Embarcador guardado",
            transit_days=43,
            freight_20=Decimal("4200"),
            freight_20_max=Decimal("4700"),
            freight_40=Decimal("5600"),
            currency="USD",
            source="Tarifa alternativa de prueba",
        )
        self.client.post("/", self.payload())
        saved_quote = QuoteHistory.objects.get(user=self.user)
        alternative.delete()
        self.legacy_rate.delete()

        response = self.client.get(
            reverse("quote_history_excel", args=(saved_quote.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn(f"cotizacion_cintac_{saved_quote.pk}.xlsx", response["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        sheet = workbook["Cotización"]
        rows = {
            row[0].value: (row[1].value, row[2].value if len(row) > 2 else None)
            for row in sheet.iter_rows(min_row=1, max_col=3)
            if row[0].value
        }
        self.assertEqual(rows["Usuario"][0], "cotizador")
        self.assertEqual(rows["Destino"][0], "San Antonio")
        self.assertEqual(rows["Flete total mínimo"], ("7.740.000", "CLP"))
        self.assertIn(
            ("Embarcador guardado", "4.200,00", "4.700,00"),
            list(sheet.iter_rows(min_row=1, max_col=3, values_only=True)),
        )


    def test_quote_history_detail_is_private_except_for_tariff_managers(self):
        self.client.post("/", self.payload())
        saved_quote = QuoteHistory.objects.get(user=self.user)
        other_user = get_user_model().objects.create_user(
            username="usuario-sin-acceso",
            first_name="Usuario",
            last_name="Compartido",
            password="Clave-segura-123",
        )
        self.client.force_login(other_user)

        response = self.client.get(
            reverse("quote_history_detail", args=(saved_quote.pk,))
        )

        self.assertEqual(response.status_code, 404)
        manager_group = Group.objects.get(name="Administración CINTAC")
        manager_group.user_set.add(other_user)
        other_user.is_staff = True
        other_user.save(update_fields=["is_staff"])
        response = self.client.get(
            reverse("quote_history_detail", args=(saved_quote.pk,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Usuario Compartido")

    def test_quote_history_detail_handles_records_without_full_snapshot(self):
        self.client.post("/", self.payload())
        saved_quote = QuoteHistory.objects.get(user=self.user)
        saved_quote.details = {}
        saved_quote.save(update_fields=["details"])

        response = self.client.get(
            reverse("quote_history_detail", args=(saved_quote.pk,))
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Esta cotización se guardó antes de habilitar el detalle completo")
        self.assertContains(response, "Resultado guardado")
        self.assertFalse(response.context["details"]["is_complete_snapshot"])

    def test_quote_history_requires_authentication(self):
        self.client.logout()

        response = self.client.get(reverse("quote_history"))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('quote_history')}")

        detail_response = self.client.get(
            reverse("quote_history_detail", args=(1,))
        )
        self.assertRedirects(
            detail_response,
            f"{reverse('login')}?next={reverse('quote_history_detail', args=(1,))}",
        )
        excel_response = self.client.get(
            reverse("quote_history_excel", args=(1,))
        )
        self.assertRedirects(
            excel_response,
            f"{reverse('login')}?next={reverse('quote_history_excel', args=(1,))}",
        )

    def test_quote_history_cannot_be_cleared_without_confirmation(self):
        self.client.post("/", self.payload())

        response = self.client.post(
            reverse("clear_quote_history"),
            {"password": "Clave-segura-123"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(QuoteHistory.objects.filter(user=self.user).count(), 1)

    def test_quote_history_cannot_be_cleared_with_wrong_password(self):
        self.client.post("/", self.payload())
        manager = self.create_history_manager()
        self.client.force_login(manager)

        response = self.client.post(
            reverse("clear_quote_history"),
            {"password": "incorrecta", "confirm_delete": "yes"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("quote_history"))
        self.assertEqual(QuoteHistory.objects.filter(user=self.user).count(), 1)
        self.assertContains(self.client.get(reverse("quote_history")), "La contraseña ingresada no es correcta")

    def test_superadmin_can_clear_own_and_other_users_quote_history(self):
        self.client.post("/", self.payload())
        other_user = get_user_model().objects.create_user(
            username="otro-cotizador",
            password="otra-clave-de-prueba",
        )
        self.client.force_login(other_user)
        self.client.post("/", self.payload())
        manager = self.create_history_manager()
        self.client.force_login(manager)
        self.client.post("/", self.payload())
        self.assertEqual(QuoteHistory.objects.count(), 3)

        history_response = self.client.get(reverse("quote_history"))
        self.assertContains(history_response, "Eliminar todo el historial")
        self.assertContains(history_response, 'name="password" type="password"')

        response = self.client.post(
            reverse("clear_quote_history"),
            {"password": "Clave-segura-123", "confirm_delete": "yes"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("quote_history"))
        self.assertEqual(QuoteHistory.objects.count(), 0)
        self.assertContains(response, "Se eliminaron 3 cotizaciones de todo el historial")

    def create_history_manager(self):
        manager = get_user_model().objects.create_user(
            username="SuperAdminCintac",
            password="Clave-segura-123",
        )
        Group.objects.get(name="Administración CINTAC").user_set.add(manager)
        return manager

    def test_quote_history_clear_requires_post(self):
        manager = self.create_history_manager()
        self.client.force_login(manager)
        response = self.client.get(reverse("clear_quote_history"))

        self.assertEqual(response.status_code, 405)

    def test_same_route_carrier_rates_can_be_compared(self):
        # Compara tarifas generales y específicas del destino, sin repetir la elegida.
        alternative = FreightRate.objects.create(
            route=self.legacy_rate.route,
            destination_port="",
            carrier="Embarcador B",
            transit_days=43,
            freight_20=Decimal("4200"),
            freight_20_max=Decimal("4700"),
            freight_40=Decimal("5600"),
            currency="USD",
        )
        response = self.client.post("/", self.payload())
        comparisons = response.context["result"]["comparisons"]
        alternative_row = next(item for item in comparisons if item["carrier"] == "Embarcador B")

        self.assertContains(response, "Embarcador B")
        self.assertContains(response, "Tarifa por contenedor")
        self.assertContains(response, "Comparación de alternativas")
        self.assertEqual(alternative_row["quantity"], 2)
        self.assertEqual(alternative_row["unit_amount"], "4.200,00")
        self.assertEqual(alternative_row["unit_amount_max"], "4.700,00")
        self.assertEqual(alternative_row["amount"], "7.560.000")
        self.assertEqual(alternative_row["amount_max"], "8.460.000")
        self.assertEqual(alternative_row["days"], 46)
        self.assertEqual(alternative_row["days_max"], None)
        self.assertNotIn(
            self.legacy_rate.pk,
            [item["rate_id"] for item in comparisons],
        )
        self.assertEqual(alternative_row["source"], alternative.source)

    def test_comparisons_convert_alternative_rates_with_a_different_currency(self):
        FreightRate.objects.create(
            route=self.legacy_rate.route,
            destination_port="San Antonio",
            carrier="Embarcador CLP",
            transit_days=40,
            transit_days_max=45,
            freight_20=Decimal("3800000"),
            freight_20_max=Decimal("4200000"),
            freight_40=Decimal("5000000"),
            currency="CLP",
        )

        response = self.client.post("/", self.payload())
        comparison = next(
            item
            for item in response.context["result"]["comparisons"]
            if item["carrier"] == "Embarcador CLP"
        )

        self.assertEqual(comparison["rate_currency"], "CLP")
        self.assertEqual(comparison["currency"], "CLP")
        self.assertEqual(comparison["unit_amount"], "3.800.000")
        self.assertEqual(comparison["unit_amount_max"], "4.200.000")
        self.assertEqual(comparison["amount"], "7.600.000")
        self.assertEqual(comparison["amount_max"], "8.400.000")
        self.assertEqual(comparison["days"], 43)
        self.assertEqual(comparison["days_max"], 48)

    def test_rates_page_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse("rates"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('rates')}")

    def test_rates_page_lists_database_values_and_provenance(self):
        response = self.client.get(reverse("rates"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tarifas cargadas")
        self.assertContains(response, "Shanghai")
        self.assertContains(response, "USD 4.300,00")
        self.assertContains(response, "San Antonio")
        self.assertContains(response, "Segucargo / Delpa Group 2026")

    def test_rates_page_uses_friendly_label_for_excel_filename(self):
        self.legacy_rate.source = "tarifas_actualizadas.xlsx · Importaciones!A2:H2"
        self.legacy_rate.save(update_fields=["source"])
        response = self.client.get(reverse("rates"))
        self.assertContains(response, "Excel de tarifas · Importaciones, fila 2")
        self.assertNotContains(response, "tarifas_actualizadas.xlsx")

    def test_rates_page_search_filters_routes(self):
        response = self.client.get(reverse("rates"), {"q": "Callao"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Callao")
        self.assertNotContains(response, "Shanghai")
        self.assertEqual(response.context["total_rates"], 1)


class TariffExcelImportTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="tariff-admin",
            email="admin@example.com",
            password="Clave-segura-123",
        )
        self.client.force_login(self.admin)
        self.import_url = reverse("admin:cotizador_freightrate_import_excel")

    def workbook_upload(self, total_20=4400):
        workbook = Workbook()
        imports = workbook.active
        imports.title = "Importaciones"
        imports.append(
            (
                "Pais",
                "Tipo Transporte",
                "Puertos Pais Origen",
                "Días Transito",
                "Cantidad Cont. 20'",
                "Flete Total 20'",
                "Cantidad Cont. 40'",
                "Flete Total 40'",
            )
        )
        imports.append(("China", "Maritimo", "Shanghai", "46 días", 1, total_20, 1, 5800))
        unit_rates = (
            ("China", 20, 4400),
            ("China", 40, 5800),
            ("Japon", 20, 5500),
            ("Japon", 40, 6700),
            ("Espana", 20, 3200),
            ("Espana", 40, 5500),
            ("EE.UU.", 20, 2500),
            ("EE.UU.", 40, 4500),
            ("Peru", 20, 1000),
            ("Peru", 40, 1200),
        )
        for row_number, (country, size, amount) in enumerate(unit_rates, start=1):
            imports.cell(row_number, 10, f"Valor Contenedor de {country} 1 de {size}")
            imports.cell(row_number, 11, amount)
        content = BytesIO()
        workbook.save(content)
        return SimpleUploadedFile(
            "tarifas_actualizadas.xlsx",
            content.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_excel_upload_updates_database_and_preserves_other_rates(self):
        old_rate = FreightRate.objects.get(
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
            carrier="",
        )
        reference_rate = FreightRate.objects.get(
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="San Antonio",
            carrier="",
        )
        rate_count = FreightRate.objects.count()

        response = self.client.post(
            self.import_url,
            {"workbook": self.workbook_upload()},
        )

        self.assertRedirects(response, reverse("admin:cotizador_freightrate_changelist"))
        old_rate.refresh_from_db()
        reference_rate.refresh_from_db()
        self.assertEqual(old_rate.freight_20, Decimal("4400.00"))
        self.assertEqual(old_rate.freight_40, Decimal("5800.00"))
        self.assertEqual(old_rate.transit_days, 46)
        self.assertEqual(old_rate.currency, "USD")
        self.assertEqual(
            old_rate.source,
            "tarifas_actualizadas.xlsx · Importaciones!A2:H2",
        )
        self.assertEqual(reference_rate.freight_20, Decimal("1600.00"))
        self.assertEqual(FreightRate.objects.count(), rate_count)
        self.assertTrue(
            any("0 tarifas nuevas y 1 actualizadas" in str(message) for message in response.wsgi_request._messages)
        )

    def test_tariff_list_links_to_excel_import_page(self):
        response = self.client.get(reverse("admin:cotizador_freightrate_changelist"))
        self.assertContains(response, "Vincular Excel de tarifas")
        self.assertContains(response, self.import_url)

    def test_reimporting_excel_updates_records_without_creating_duplicates(self):
        rate_count = FreightRate.objects.count()
        for _ in range(2):
            response = self.client.post(
                self.import_url,
                {"workbook": self.workbook_upload()},
            )
            self.assertEqual(response.status_code, 302)
        self.assertEqual(FreightRate.objects.count(), rate_count)

    def test_excel_upload_rejects_totals_that_do_not_match_unit_values(self):
        rate = FreightRate.objects.get(
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
            carrier="",
        )

        response = self.client.post(
            self.import_url,
            {"workbook": self.workbook_upload(total_20=4500)},
        )

        rate.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no coincide")
        self.assertEqual(rate.freight_20, Decimal("4300.00"))

    def test_excel_upload_does_not_require_other_sheets(self):
        rate = FreightRate.objects.get(
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
            carrier="",
        )
        response = self.client.post(
            self.import_url,
            {"workbook": self.workbook_upload()},
        )
        rate.refresh_from_db()
        self.assertRedirects(response, reverse("admin:cotizador_freightrate_changelist"))
        self.assertEqual(rate.freight_20, Decimal("4400.00"))


class TariffManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="tariff-manager",
            email="manager@example.com",
            password="Clave-segura-123",
        )
        self.client.force_login(self.admin)
        self.test_route = Route.objects.create(
            country="País de prueba",
            origin_port="Puerto de prueba",
        )
        FreightRate.objects.create(
            route=self.test_route,
            transit_days=10,
            freight_20=Decimal("1000"),
            freight_40=Decimal("1800"),
            currency="USD",
        )

    def tariff_payload(self):
        return {
            "origin_route": f"route:{self.test_route.pk}",
            "destination_port": "Valparaíso",
            "carrier": "",
            "route_type": "Directo",
            "transit_days": "12",
            "transit_days_max": "",
            "freight_20": "1000.00",
            "freight_20_max": "",
            "freight_40": "1800.00",
            "freight_40_max": "",
            "currency": "USD",
            "source": "Tarifa ingresada por administración",
        }

    def create_tariff(self):
        response = self.client.post(reverse("rate_create"), self.tariff_payload())
        self.assertRedirects(
            response,
            reverse("rates"),
            msg_prefix=str(response.context["form"].errors) if response.status_code == 200 else "",
        )
        return FreightRate.objects.get(
            operation="import",
            route=self.test_route,
            destination_port="Valparaíso",
            carrier="",
        )

    def test_admin_can_create_import_tariff(self):
        rate = self.create_tariff()
        self.assertEqual(rate.operation, "import")
        self.assertEqual(rate.currency, "USD")

    def test_route_admin_rejects_chilean_origins(self):
        form = ImportRouteAdminForm(
            data={"country": "Chile", "origin_port": "Valparaíso"}
        )

        self.assertFalse(form.is_valid())
        self.assertIn("country", form.errors)

    def test_admin_can_edit_existing_import_tariff(self):
        rate = self.create_tariff()
        payload = self.tariff_payload()
        payload.update(
            {
                "origin_route": f"route:{rate.route_id}",
                "freight_20": "1050.00",
                "transit_days": "13",
            }
        )
        response = self.client.post(reverse("rate_edit", args=(rate.pk,)), payload)

        self.assertRedirects(response, reverse("rates"))
        rate.refresh_from_db()
        self.assertEqual(rate.operation, "import")
        self.assertEqual(rate.freight_20, Decimal("1050.00"))
        self.assertEqual(rate.transit_days, 13)

    def test_admin_can_edit_a_preloaded_import_tariff(self):
        rate = FreightRate.objects.get(
            operation="import",
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
            carrier="",
        )
        payload = self.tariff_payload()
        payload.update(
            {
                "origin_route": f"route:{rate.route_id}",
                "destination_port": rate.destination_port,
                "carrier": rate.carrier,
                "freight_20": "4350.00",
                "transit_days": "44",
                "source": rate.source,
            }
        )
        response = self.client.post(reverse("rate_edit", args=(rate.pk,)), payload)

        self.assertRedirects(response, reverse("rates"))
        rate.refresh_from_db()
        self.assertEqual(rate.freight_20, Decimal("4350.00"))
        self.assertEqual(rate.transit_days, 44)

    def test_tariff_form_fields_are_select_menus(self):
        response = self.client.get(reverse("rate_create"))
        form = response.context["form"]
        self.assertTrue(all(isinstance(field.widget, forms.Select) for field in form.fields.values()))
        self.assertEqual(form.fields["freight_20"].choices[-1][0], "20000.00")
        self.assertEqual(form.fields["transit_days"].choices[-1][0], 120)

    def test_catalog_choices_are_rendered_in_the_select_widgets(self):
        form = self.client.get(reverse("rate_create")).context["form"]

        for field_name in ("origin_route", "destination_port", "carrier", "route_type", "source"):
            with self.subTest(field=field_name):
                rendered_options = str(form[field_name]).count("<option")
                self.assertEqual(rendered_options, len(form.fields[field_name].choices))
        self.assertIn("Shanghai, China", str(form["origin_route"]))
        self.assertIn("San Antonio, Chile", str(form["destination_port"]))

    def test_admin_cannot_register_a_carrier_not_in_the_existing_catalog(self):
        payload = self.tariff_payload()
        payload["carrier"] = "Embarcador Nuevo"

        response = self.client.post(reverse("rate_create"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertIn("carrier", response.context["form"].errors)
        self.assertFalse(FreightRate.objects.filter(carrier="Embarcador Nuevo").exists())

    def test_admin_can_edit_from_the_tariff_list(self):
        response = self.client.get(reverse("rates"))
        rate = FreightRate.objects.get(
            operation="import",
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
        )
        self.assertContains(response, reverse("rate_edit", args=(rate.pk,)))

    def test_rate_form_uses_the_selected_currency_limits(self):
        usd_form = FreightRateEntryForm()
        clp_form = FreightRateEntryForm(data={"currency": "CLP"})

        self.assertEqual(usd_form.fields["freight_20"].choices[-1][0], "20000.00")
        self.assertEqual(clp_form.fields["freight_20"].choices[-1][0], "20000000.00")
        self.assertNotIn("20050.00", clp_form.fields["freight_20"].choices)

    def test_rate_form_rejects_values_outside_select_catalogs(self):
        payload = self.tariff_payload()
        payload["freight_20"] = "1025.00"
        payload["transit_days"] = "121"
        response = self.client.post(reverse("rate_create"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertIn("freight_20", response.context["form"].errors)
        self.assertIn("transit_days", response.context["form"].errors)
        self.assertFalse(FreightRate.objects.filter(route__country="Chile").exists())

    def test_admin_deletes_only_selected_rate_after_confirmation(self):
        import_rate = self.create_tariff()
        other_rate = FreightRate.objects.get(
            operation="import",
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
        )
        delete_url = reverse("rate_delete", args=(import_rate.pk,))

        confirmation = self.client.get(delete_url)
        self.assertEqual(confirmation.status_code, 200)
        self.assertTrue(FreightRate.objects.filter(pk=import_rate.pk).exists())
        response = self.client.post(delete_url)

        self.assertRedirects(response, reverse("rates"))
        self.assertFalse(FreightRate.objects.filter(pk=import_rate.pk).exists())
        self.assertTrue(FreightRate.objects.filter(pk=other_rate.pk).exists())

    def test_non_admin_user_cannot_create_or_delete_tariffs(self):
        rate = FreightRate.objects.get(
            operation="import",
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
        )
        user = get_user_model().objects.create_user(
            username="regular-user",
            password="Clave-segura-123",
        )
        self.client.force_login(user)

        create_response = self.client.get(reverse("rate_create"))
        edit_response = self.client.get(reverse("rate_edit", args=(rate.pk,)))
        delete_response = self.client.post(reverse("rate_delete", args=(rate.pk,)))
        rates_response = self.client.get(reverse("rates"))

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(edit_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.assertNotContains(rates_response, "Cargar tarifa")
        self.assertNotContains(rates_response, "Eliminar")
        self.assertTrue(FreightRate.objects.filter(pk=rate.pk).exists())

    def test_user_with_direct_model_permissions_cannot_manage_tariffs_without_role(self):
        user = get_user_model().objects.create_user(
            username="permission-only-user",
            password="Clave-segura-123",
            is_staff=True,
        )
        user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="cotizador",
                codename__in=(
                    "add_freightrate",
                    "change_freightrate",
                    "delete_freightrate",
                    "view_freightrate",
                ),
            )
        )
        self.client.force_login(user)

        response = self.client.get(reverse("rate_create"))
        admin_response = self.client.get(
            reverse("admin:cotizador_freightrate_changelist")
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(admin_response.status_code, 403)


class CintacManagerAdminTests(TestCase):
    def setUp(self):
        self.manager = get_user_model().objects.create_user(
            username="cintac-manager",
            password="Clave-segura-123",
            is_staff=True,
        )
        self.role = Group.objects.get(name="Administración CINTAC")
        self.role.user_set.add(self.manager)
        self.client.force_login(self.manager)

    def test_manager_can_open_user_history_and_tariff_admin_sections(self):
        for url in (
            reverse("admin:auth_user_changelist"),
            reverse("admin:cotizador_quotehistory_changelist"),
            reverse("admin:cotizador_freightrate_changelist"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        self.assertEqual(
            self.client.get(reverse("admin:auth_group_changelist")).status_code,
            403,
        )

    def test_regular_tariff_admin_cannot_delete_quote_history_or_users(self):
        quote = QuoteHistory.objects.create(
            user=self.manager,
            operation="import",
            origin_port="Shanghai",
            origin_country="China",
            destination="San Antonio",
            container_size="20",
            weight=Decimal("10"),
            weight_unit="ton",
            tonnes=Decimal("10"),
            container_quantity=1,
            source_currency="USD",
            currency="USD",
            amount=Decimal("100"),
            base_days=30,
            total_days=30,
        )

        history_delete_response = self.client.get(
            reverse("admin:cotizador_quotehistory_delete", args=(quote.pk,))
        )
        target_user = get_user_model().objects.create_user(
            username="usuario-regular",
            password="Clave-segura-123",
        )
        user_delete_response = self.client.get(
            reverse("admin:auth_user_delete", args=(target_user.pk,))
        )
        clear_history_response = self.client.post(
            reverse("clear_quote_history"),
            {"confirm_delete": "yes"},
        )
        users_admin_response = self.client.get(reverse("admin:auth_user_changelist"))

        self.assertEqual(history_delete_response.status_code, 403)
        self.assertEqual(user_delete_response.status_code, 403)
        self.assertEqual(clear_history_response.status_code, 403)
        self.assertNotContains(users_admin_response, "delete_selected")

    def test_manager_can_open_tariff_editor(self):
        rate = FreightRate.objects.first()
        response = self.client.get(reverse("rate_edit", args=(rate.pk,)))

        self.assertEqual(response.status_code, 200)

    def test_manager_can_create_regular_users_without_assigning_privileges(self):
        add_url = reverse("admin:auth_user_add")
        self.assertEqual(self.client.get(add_url).status_code, 200)
        response = self.client.post(
            add_url,
            {
                "username": "created-by-manager",
                "password1": "Una-clave-segura-987",
                "password2": "Una-clave-segura-987",
                "email": "new@example.com",
                "first_name": "Nuevo",
                "last_name": "Usuario",
                "is_staff": "on",
                "is_superuser": "on",
                "groups": [self.role.pk],
            },
        )
        self.assertEqual(response.status_code, 302)

        created_user = get_user_model().objects.get(username="created-by-manager")
        self.assertFalse(created_user.is_staff)
        self.assertFalse(created_user.is_superuser)
        self.assertFalse(created_user.groups.exists())

    def test_manager_cannot_edit_or_delete_another_administrator(self):
        another_manager = get_user_model().objects.create_user(
            username="another-manager",
            password="Clave-segura-456",
            is_staff=True,
        )
        self.role.user_set.add(another_manager)

        edit_response = self.client.get(
            reverse("admin:auth_user_change", args=(another_manager.pk,))
        )
        delete_response = self.client.get(
            reverse("admin:auth_user_delete", args=(another_manager.pk,))
        )

        self.assertEqual(edit_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)


class UserManagementPageTests(TestCase):
    def setUp(self):
        self.manager = get_user_model().objects.create_user(
            username="SuperAdminCintac",
            password="Clave-segura-123",
            is_staff=True,
        )
        self.role = Group.objects.get(name="Administración CINTAC")
        self.role.user_set.add(self.manager)
        self.client.force_login(self.manager)

    def test_only_named_manager_can_open_the_user_management_page(self):
        get_user_model().objects.create_user(
            username="listed-user",
            password="Clave-segura-123",
        )
        response = self.client.get(reverse("manage_users"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Administrar usuarios")
        self.assertContains(response, "Al eliminar una cuenta también se borran")
        self.assertContains(response, "listed-user")
        self.assertContains(response, "confirm(")

        other_manager = get_user_model().objects.create_user(
            username="another-manager",
            password="Clave-segura-456",
            is_staff=True,
        )
        self.role.user_set.add(other_manager)
        self.client.force_login(other_manager)
        self.assertEqual(self.client.get(reverse("manage_users")).status_code, 403)

    def test_manager_can_delete_regular_user_with_post(self):
        target = get_user_model().objects.create_user(
            username="user-to-delete",
            password="Clave-segura-789",
        )
        url = reverse("delete_managed_user", args=(target.pk,))

        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)

        self.assertRedirects(response, reverse("manage_users"))
        self.assertFalse(get_user_model().objects.filter(pk=target.pk).exists())

    def test_manager_cannot_delete_self_or_superusers(self):
        superuser = get_user_model().objects.create_superuser(
            username="protected-superuser",
            email="protected@example.com",
            password="Clave-segura-999",
        )

        for protected_user in (self.manager, superuser):
            with self.subTest(username=protected_user.username):
                response = self.client.post(
                    reverse("delete_managed_user", args=(protected_user.pk,))
                )
                self.assertEqual(response.status_code, 404)
                self.assertTrue(
                    get_user_model().objects.filter(pk=protected_user.pk).exists()
                )

    def test_manager_can_create_user_with_profile_and_password(self):
        response = self.client.post(
            reverse("create_managed_user"),
            {
                "username": "new-managed-user",
                "email": "new-managed@example.com",
                "first_name": "Nombre",
                "last_name": "Apellido",
                "rut": "12.345.678-9",
                "password1": "Una-clave-segura-987!",
                "password2": "Una-clave-segura-987!",
            },
        )

        self.assertRedirects(response, reverse("manage_users"))
        user = get_user_model().objects.get(username="new-managed-user")
        self.assertEqual(user.email, "new-managed@example.com")
        self.assertEqual(user.first_name, "Nombre")
        self.assertEqual(user.last_name, "Apellido")
        self.assertTrue(user.check_password("Una-clave-segura-987!"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.profile.rut, "12.345.678-9")

    def test_manager_cannot_create_username_that_already_exists(self):
        get_user_model().objects.create_user(
            username="existing-user",
            password="Clave-segura-123",
        )

        for username in ("existing-user", "EXISTING-USER"):
            with self.subTest(username=username):
                response = self.client.post(
                    reverse("create_managed_user"),
                    {
                        "username": username,
                        "email": f"{username}@example.com",
                        "first_name": "Nuevo",
                        "last_name": "Usuario",
                        "rut": "",
                        "password1": "Una-clave-segura-987!",
                        "password2": "Una-clave-segura-987!",
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("username", response.context["form"].errors)
        self.assertEqual(get_user_model().objects.filter(username__iexact="existing-user").count(), 1)

    def test_manager_can_edit_user_details_and_change_password(self):
        user = get_user_model().objects.create_user(
            username="managed-user",
            password="Clave-anterior-987!",
            email="old@example.com",
        )
        response = self.client.post(
            reverse("edit_managed_user", args=(user.pk,)),
            {
                "username": "updated-user",
                "email": "updated@example.com",
                "first_name": "Nuevo nombre",
                "last_name": "Nuevo apellido",
                "rut": "11.222.333-4",
                "password1": "Clave-nueva-segura-654!",
                "password2": "Clave-nueva-segura-654!",
            },
        )

        self.assertRedirects(response, reverse("manage_users"))
        user.refresh_from_db()
        self.assertEqual(user.username, "updated-user")
        self.assertEqual(user.email, "updated@example.com")
        self.assertEqual(user.first_name, "Nuevo nombre")
        self.assertEqual(user.last_name, "Nuevo apellido")
        self.assertEqual(user.profile.rut, "11.222.333-4")
        self.assertTrue(user.check_password("Clave-nueva-segura-654!"))
        self.assertFalse(user.check_password("Clave-anterior-987!"))

    def test_manager_can_edit_user_without_changing_password(self):
        user = get_user_model().objects.create_user(
            username="unchanged-password-user",
            password="Clave-anterior-987!",
            email="old@example.com",
        )
        response = self.client.post(
            reverse("edit_managed_user", args=(user.pk,)),
            {
                "username": user.username,
                "email": "updated@example.com",
                "first_name": "Nombre",
                "last_name": "Apellido",
                "rut": "",
                "password1": "",
                "password2": "",
            },
        )

        self.assertRedirects(response, reverse("manage_users"))
        user.refresh_from_db()
        self.assertEqual(user.email, "updated@example.com")
        self.assertTrue(user.check_password("Clave-anterior-987!"))

    def test_manager_cannot_change_username_to_another_existing_username(self):
        get_user_model().objects.create_user(
            username="existing-user",
            password="Clave-segura-123",
        )
        user = get_user_model().objects.create_user(
            username="managed-user",
            password="Clave-segura-456",
            email="managed@example.com",
        )
        response = self.client.post(
            reverse("edit_managed_user", args=(user.pk,)),
            {
                "username": "EXISTING-USER",
                "email": "managed@example.com",
                "first_name": "Nombre",
                "last_name": "Apellido",
                "rut": "",
                "password1": "",
                "password2": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        user.refresh_from_db()
        self.assertEqual(user.username, "managed-user")

    def test_manager_cannot_change_another_admin_or_self(self):
        another_manager = get_user_model().objects.create_user(
            username="another-manager",
            password="Clave-segura-456!",
            is_staff=True,
        )
        self.role.user_set.add(another_manager)

        self.assertEqual(
            self.client.get(
                reverse("edit_managed_user", args=(another_manager.pk,))
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("edit_managed_user", args=(self.manager.pk,))
            ).status_code,
            404,
        )


class UserProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="profile-user",
            password="Clave-segura-123",
            email="antes@example.com",
        )
        self.client.force_login(self.user)

    def test_profile_requires_authentication(self):
        self.client.logout()

        response = self.client.get(reverse("user_profile"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('user_profile')}",
        )

    def test_profile_photo_can_be_removed_without_django_clear_control(self):
        image = BytesIO()
        Image.new("RGB", (8, 8), color="orange").save(image, format="PNG")
        image.seek(0)

        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                profile = self.user.profile
                profile.avatar.save(
                    "perfil.png",
                    SimpleUploadedFile("perfil.png", image.read(), content_type="image/png"),
                    save=True,
                )

                page = self.client.get(reverse("user_profile"))
                self.assertContains(page, "Editar foto de perfil")
                self.assertContains(page, "Quitar foto de perfil")
                self.assertContains(page, 'id="profile-details"')
                self.assertContains(page, 'id="profile-edit-form" hidden')
                self.assertContains(page, "Editar perfil")
                self.assertContains(page, "antes@example.com")
                self.assertContains(page, 'name="avatar-clear"')
                self.assertContains(page, "cotizador/profile.js")
                self.assertNotContains(page, "Clear")

                response = self.client.post(
                    reverse("user_profile"),
                    {
                        "first_name": "Perfil",
                        "last_name": "",
                        "email": "antes@example.com",
                        "rut": "",
                        "avatar-clear": "on",
                    },
                )

                self.assertRedirects(response, reverse("user_profile"))
                profile.refresh_from_db()
                self.assertFalse(profile.avatar)

    def test_profile_updates_account_details_and_photo_for_current_user(self):
        image = BytesIO()
        Image.new("RGB", (8, 8), color="orange").save(image, format="PNG")
        image.seek(0)
        upload = SimpleUploadedFile("perfil.png", image.read(), content_type="image/png")

        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    reverse("user_profile"),
                    {
                        "first_name": "María",
                        "last_name": "Pérez",
                        "email": "maria@example.com",
                        "rut": "12.345.678-9",
                        "avatar": upload,
                    },
                )

                self.assertRedirects(response, reverse("user_profile"))
                self.user.refresh_from_db()
                profile = UserProfile.objects.get(user=self.user)
                self.assertEqual(self.user.first_name, "María")
                self.assertEqual(self.user.last_name, "Pérez")
                self.assertEqual(self.user.email, "maria@example.com")
                self.assertEqual(profile.rut, "12.345.678-9")
                self.assertTrue(profile.avatar.name.startswith("profile_photos/"))
                self.assertTrue(profile.avatar.storage.exists(profile.avatar.name))
                profile_response = self.client.get(reverse("user_profile"))
                self.assertContains(profile_response, "María Pérez")
                self.assertContains(profile_response, "maria@example.com")
                self.assertContains(profile_response, "12.345.678-9")
                self.assertContains(profile_response, profile.avatar.url)

    def test_profile_rejects_non_image_upload_without_saving_other_changes(self):
        response = self.client.post(
            reverse("user_profile"),
            {
                "first_name": "Nombre no guardado",
                "last_name": "",
                "email": "nuevo@example.com",
                "rut": "",
                "avatar": SimpleUploadedFile(
                    "perfil.png",
                    b"esto no es una imagen",
                    content_type="image/png",
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("avatar", response.context["form"].errors)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "")
        self.assertEqual(self.user.email, "antes@example.com")
