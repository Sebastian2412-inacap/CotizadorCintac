# Valores decimales y utilidades de prueba de Django.
from io import BytesIO
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from openpyxl import Workbook, load_workbook

# Modelo y servicios cuyo comportamiento se valida.
from .forms import FreightRateEntryForm
from .models import FreightRate, Route
from .services import DESTINATIONS, container_count, convert_currency


# Pruebas aisladas de cálculos que no necesitan acceso a la base de datos.
class CalculationTests(SimpleTestCase):
    def test_container_capacity_rounds_up_at_25_tonnes(self):
        # Comprueba el límite de capacidad y que los kilogramos se conviertan.
        self.assertEqual(container_count("25", "ton"), (Decimal("25"), 1))
        self.assertEqual(container_count("26", "ton"), (Decimal("26"), 2))
        self.assertEqual(container_count("26000", "kg"), (Decimal("26"), 2))

    def test_currency_conversion_uses_user_supplied_rate(self):
        # Verifica conversiones en ambos sentidos y moneda de destino idéntica.
        self.assertEqual(convert_currency("100", "USD", "CLP", "900"), Decimal("90000"))
        self.assertEqual(convert_currency("90000", "CLP", "USD", "900"), Decimal("100"))
        self.assertEqual(convert_currency("100", "USD", "USD", ""), Decimal("100"))

    def test_chilean_destinations_are_available(self):
        # Asegura que existan destinos clave en las opciones admitidas.
        self.assertEqual(DESTINATIONS[0], "Arica")
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
            "container_size": "20",
            "margin_days": "3",
            "target_currency": "",
            "exchange_rate": "",
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
        for url in (reverse("quote"), reverse("rates")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response["Cache-Control"])

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

    def test_legacy_maritime_quote_uses_usd_and_days(self):
        # Verifica total, contenedores, tránsito y destino de una cotización.
        response = self.client.post("/", self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 contenedores")
        self.assertContains(response, "8.600,00")
        self.assertContains(response, "48 días")
        self.assertContains(response, "FLETE BASE · USD")
        self.assertContains(response, "San Antonio")

    def test_reference_quote_displays_price_and_transit_ranges(self):
        # Comprueba la presentación de rangos de flete y días de tránsito.
        response = self.client.post("/", self.payload(rate=self.reference_rate))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3.200,00 – 5.600,00")
        self.assertContains(response, "25–32 días")
        self.assertContains(response, "28–35 días")
        self.assertContains(response, "Segucargo / Delpa Group 2026")

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
        self.assertEqual(rows["Flete total mínimo"], ("8.600,00", "USD"))
        self.assertEqual(rows["Cantidad de contenedores"][0], 2)
        self.assertEqual(rows["Destino"][0], "San Antonio")
        self.assertIn("Comparación de alternativas", rows)

    def test_reference_rate_forces_its_validated_destination(self):
        # Evita que el selector contradiga el destino asociado a la tarifa.
        response = self.client.post(
            "/",
            self.payload(rate=self.reference_rate, destination="Valparaíso"),
        )
        self.assertEqual(response.context["result"]["destination"], "San Antonio")
        self.assertEqual(response.context["form"]["destination"], "San Antonio")

    def test_air_quote_is_not_calculated_without_rates(self):
        # Confirma que no se muestre cálculo si faltan tarifas aéreas.
        response = self.client.post("/", self.payload(transport="air"))
        self.assertContains(response, "No hay tarifas aéreas cargadas")
        self.assertNotContains(response, "2 contenedores")

    def test_export_quote_is_not_calculated_without_rates(self):
        # Confirma que no se cotice una exportación sin datos disponibles.
        response = self.client.post("/", self.payload(operation="export"))
        self.assertContains(response, "No hay tarifas de exportación cargadas")

    def test_usd_rate_can_be_converted_to_clp(self):
        # Comprueba que se aplique el tipo de cambio indicado por el usuario.
        response = self.client.post(
            "/",
            self.payload(target_currency="CLP", exchange_rate="900"),
        )
        self.assertContains(response, "7.740.000,00")
        self.assertContains(response, "FLETE BASE · CLP")

    def test_same_route_carrier_rates_can_be_compared(self):
        # Añade un transportista alternativo y verifica que aparezca comparado.
        FreightRate.objects.create(
            route=self.legacy_rate.route,
            destination_port="",
            carrier="Embarcador B",
            transit_days=43,
            freight_20=Decimal("4200"),
            freight_40=Decimal("5600"),
            currency="USD",
        )
        response = self.client.post("/", self.payload())
        self.assertContains(response, "Embarcador B")
        self.assertContains(response, "Comparación de alternativas")

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
        self.legacy_rate.source = (
            "Prompts Importaciones - Exportaciones (1) (1).xlsx · Importaciones!A2:H2"
        )
        self.legacy_rate.save(update_fields=["source"])
        response = self.client.get(reverse("rates"))
        self.assertContains(response, "Excel de tarifas · Importaciones, fila 2")
        self.assertNotContains(response, "Prompts Importaciones")

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

    def workbook_upload(self, total_20=4400, export_row=None):
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
        exports = workbook.create_sheet("Exportaciones")
        exports.append(("Pais", "Tipo Transporte"))
        if export_row:
            exports.append(export_row)

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
        export_route, _ = Route.objects.get_or_create(country="Chile", origin_port="San Antonio")
        export_rate = FreightRate.objects.create(
            route=export_route,
            operation="export",
            destination_port="Callao, Perú",
            carrier="Exportador existente",
            transit_days=12,
            freight_20=Decimal("900"),
            freight_40=Decimal("1700"),
            currency="USD",
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
        export_rate.refresh_from_db()
        self.assertEqual(export_rate.freight_20, Decimal("900.00"))
        self.assertEqual(export_rate.operation, "export")
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

    def test_excel_upload_rejects_export_rows_without_changing_database(self):
        rate = FreightRate.objects.get(
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
            carrier="",
        )

        response = self.client.post(
            self.import_url,
            {"workbook": self.workbook_upload(export_row=("Chile", "Maritimo"))},
        )

        rate.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La hoja Exportaciones contiene datos")
        self.assertEqual(rate.freight_20, Decimal("4300.00"))


class TariffManagementTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="tariff-manager",
            email="manager@example.com",
            password="Clave-segura-123",
        )
        self.client.force_login(self.admin)

    def tariff_payload(self, operation="export"):
        route = Route.objects.filter(country="Chile", origin_port="San Antonio").first()
        return {
            "operation": operation,
            "origin_route": f"route:{route.pk}" if route and route.rates.exists() else "catalog:Chile|San Antonio",
            "destination_port": "Callao, Perú" if operation == "export" else "",
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

    def create_tariff(self, operation="export"):
        response = self.client.post(reverse("rate_create"), self.tariff_payload(operation))
        self.assertRedirects(response, reverse("rates"))
        return FreightRate.objects.get(
            operation=operation,
            route__country="Chile",
            route__origin_port="San Antonio",
            destination_port="Callao, Perú" if operation == "export" else "",
            carrier="",
        )

    def test_admin_can_create_import_and_export_records(self):
        for operation in ("import", "export"):
            rate = self.create_tariff(operation)
            self.assertEqual(rate.operation, operation)
            self.assertEqual(rate.currency, "USD")

    def test_export_form_only_accepts_chilean_origin_routes(self):
        china_route = Route.objects.get(country="China", origin_port="Shanghai")
        payload = self.tariff_payload("export")
        payload["origin_route"] = f"route:{china_route.pk}"

        response = self.client.post(reverse("rate_create"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertIn("origin_route", response.context["form"].errors)
        self.assertFalse(FreightRate.objects.filter(operation="export").exists())

    def test_export_tariff_is_available_to_export_quote_only(self):
        rate = self.create_tariff("export")
        response = self.client.post(
            reverse("quote"),
            {
                "operation": "export",
                "transport": "sea",
                "rate_id": rate.pk,
                "destination": rate.destination_port,
                "weight": "26000",
                "weight_unit": "kg",
                "container_size": "20",
                "margin_days": "0",
                "target_currency": "",
                "exchange_rate": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["result"]["destination"], "Callao, Perú")
        self.assertContains(response, "2 contenedores")
        self.assertContains(response, "2.000,00")
        self.assertContains(response, "Tarifa ingresada por administración")

    def test_admin_can_edit_existing_import_and_export_tariffs(self):
        for operation in ("import", "export"):
            rate = self.create_tariff(operation)
            payload = self.tariff_payload(operation)
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
            self.assertEqual(rate.operation, operation)
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
        payload = self.tariff_payload("import")
        payload.update(
            {
                "origin_route": f"route:{rate.route_id}",
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

    def test_tariff_form_fields_are_all_select_menus(self):
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
        payload = self.tariff_payload("export")
        payload["freight_20"] = "1025.00"
        payload["transit_days"] = "121"
        response = self.client.post(reverse("rate_create"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertIn("freight_20", response.context["form"].errors)
        self.assertIn("transit_days", response.context["form"].errors)
        self.assertFalse(FreightRate.objects.filter(route__country="Chile").exists())

    def test_export_quote_rejects_import_tariff_id(self):
        export_rate = self.create_tariff("export")
        import_rate = FreightRate.objects.get(
            operation="import",
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
        )
        response = self.client.post(
            reverse("quote"),
            {
                "operation": "export",
                "transport": "sea",
                "rate_id": import_rate.pk,
                "destination": export_rate.destination_port,
                "weight": "26000",
                "weight_unit": "kg",
                "container_size": "20",
                "margin_days": "0",
                "target_currency": "",
                "exchange_rate": "",
            },
        )
        self.assertContains(response, "Selecciona una tarifa de origen válida")
        self.assertNotContains(response, "8.600,00")

    def test_admin_deletes_only_selected_rate_after_confirmation(self):
        export_rate = self.create_tariff("export")
        import_rate = self.create_tariff("import")
        other_rate = FreightRate.objects.get(
            operation="import",
            route__country="China",
            route__origin_port="Shanghai",
            destination_port="",
        )
        delete_url = reverse("rate_delete", args=(export_rate.pk,))

        confirmation = self.client.get(delete_url)
        self.assertEqual(confirmation.status_code, 200)
        self.assertTrue(FreightRate.objects.filter(pk=export_rate.pk).exists())
        response = self.client.post(delete_url)

        self.assertRedirects(response, reverse("rates"))
        self.assertFalse(FreightRate.objects.filter(pk=export_rate.pk).exists())
        self.assertTrue(FreightRate.objects.filter(pk=import_rate.pk).exists())

        self.client.post(reverse("rate_delete", args=(import_rate.pk,)))
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
