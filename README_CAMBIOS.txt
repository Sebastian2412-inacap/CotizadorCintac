CAMBIOS REALIZADOS EN EL COTIZADOR CINTAC
=========================================

1. Se corrigieron las tarifas iniciales del informe para utilizar USD en vez de CLP.
2. FreightRate ahora admite:
   - Puerto de destino.
   - Rango mínimo/máximo para contenedor de 20 pies.
   - Rango mínimo/máximo para contenedor de 40 pies.
   - Tránsito mínimo/máximo.
   - Tipo de ruta.
   - Fuente/referencia.
3. Se agregaron 16 rutas referenciales consistentes desde "Cotizador - Calculadora.xlsx".
4. No se importaron las filas inconsistentes asociadas a Singapur ni fuentes dudosas del Excel.
5. El formulario sincroniza el destino cuando una tarifa referencial está vinculada a una ruta concreta.
6. El resultado muestra rangos de precio, tránsito, tipo de ruta y fuente cuando están disponibles.
7. El administrador de Django permite editar los nuevos campos.
8. Se actualizaron las pruebas automatizadas.

VERIFICACION
------------
- python manage.py makemigrations --check --dry-run : sin cambios pendientes.
- python manage.py check : sin errores.
- python manage.py test : pruebas automatizadas aprobadas.

Acceso de usuarios
------------------
- Fuera del entorno local, configura la variable de entorno DJANGO_SECRET_KEY con una clave segura.
- La portada del cotizador requiere una cuenta autenticada.
- No hay registro público; un administrador crea las cuentas desde /admin/.
- Para crear la primera cuenta administradora: python manage.py createsuperuser
- Inicio de sesión: /accounts/login/
- Tras tres intentos fallidos de contraseña, el inicio de sesión bloquea esa sesión durante 10 segundos y muestra una cuenta regresiva.
- Cierre de sesión: botón "Cerrar sesión" dentro del cotizador. Las vistas protegidas no se guardan en caché; al usar Atrás después de salir, se solicita el inicio de sesión nuevamente.

Vinculación de tarifas con Excel
--------------------------------
- En Administración > Tarifas usa "Vincular Excel de tarifas" para cargar el .xlsx.
- El libro adjunto contiene 14 tarifas en Importaciones; Exportaciones está vacía.
- Importaciones se valida antes de modificar la base de datos y se procesa en una transacción.
- Las rutas se vinculan por país y puerto de origen; las tarifas generales existentes se actualizan sin duplicarse.
- Los montos se guardan en USD, confirmado para este archivo.
- Solo se admiten importaciones marítimas con las columnas y los valores unitarios esperados.
- El total almacenado en el Excel debe coincidir con cantidad × valor unitario; guarda/recalcula el libro antes de cargarlo.
- La hoja Exportaciones está vacía; si contiene datos, se rechaza el archivo completo y no se modifica la base.
- Otras rutas, tarifas de destino y referencias existentes no se eliminan ni se alteran.
- Cada tarifa importada conserva el nombre del archivo y número de fila como referencia verificable.
- El archivo no se sincroniza automáticamente desde Descargas: vuelve a cargar la versión actualizada para aplicar cambios.

Vista de tarifas
----------------
- La opción "Tarifas" abre /tarifas/ para consultar los antecedentes almacenados.
- Incluye búsqueda por país, origen, destino, embarcador, tipo de ruta o fuente; los resultados están paginados.
- Muestra rangos de precio, moneda, tránsito, fuente y última actualización.
- Requiere iniciar sesión; es una vista de consulta y la edición/importación sigue en Administración.

Registro de importaciones y exportaciones
-----------------------------------------
- El tipo de operación se guarda por tarifa en la base de datos; las tarifas existentes se clasifican como importaciones.
- Los administradores pueden cargar tarifas manualmente desde Tarifas > Cargar tarifa y eliminarlas con confirmación.
- Los administradores pueden editar cada tarifa existente desde la lista de Tarifas.
- Todos los campos del alta/edición usan menús de selección cerrados; los fletes USD van de 0 a 20.000 en pasos de 50, CLP de 0 a 20.000.000 en pasos de 10.000 y el tránsito de 1 a 120 días.
- Los selectores de origen, destino, tipo de ruta y referencia muestran opciones del catálogo y de las tarifas existentes. Los orígenes se identifican como importación o exportación; si no hay embarcadores registrados, el menú indica “Sin especificar”.
- El origen de una exportación queda limitado a Chile y los destinos se eligen del catálogo de puertos disponibles.
- Para exportar, registra Chile y el puerto de salida como origen y el puerto internacional como destino.
- Los usuarios registrados consultan y cotizan con las tarifas de la operación seleccionada; las tarifas antiguas quedan clasificadas como importación.
- La importación del Excel actualiza solo tarifas de importación y conserva las tarifas de exportación.

Para iniciar en Windows:
1. Abrir PowerShell en la carpeta CINTAC\mi_proyecto.
2. Si PowerShell bloquea la activacion, permitir scripts solo en esta terminal:
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
3. Activar el entorno: ..\.venv\Scripts\Activate.ps1
4. Aplicar migraciones cuando corresponda: python manage.py migrate
5. Iniciar el servidor: python manage.py runserver

La politica Bypass anterior solo dura mientras esta abierta esa terminal y no
cambia la politica permanente de Windows. En VS Code, las terminales nuevas
tambien estan configuradas para activar automaticamente CINTAC\.venv.