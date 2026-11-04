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
- El grupo "Administración CINTAC" permite administrar usuarios, ver y eliminar el historial de todos los usuarios y editar, importar o eliminar tarifas. Para asignarlo a una cuenta, inicia sesión como superusuario en /admin/, crea o edita el usuario, activa "Estado del personal" y agrega el grupo "Administración CINTAC". No marques "Estado de superusuario". Solo los superusuarios pueden asignar este grupo.
- La cuenta `SuperAdminCintac` dispone del enlace "Administrar usuarios" dentro del cotizador para crear, buscar, editar y eliminar cuentas sin entrar a Django Admin. Puede establecer correo, usuario, contraseña, nombre, apellido y RUT; al editar, la contraseña es opcional. Al borrar se eliminan también las cotizaciones y el perfil asociados; no se permite modificar o eliminar su propia cuenta, superusuarios ni otras cuentas del grupo de administración.
- Los usuarios normales solo consultan y eliminan sus propias cotizaciones. El administrador CINTAC gestiona el historial global en Administración > Historial de cotizaciones y puede borrar registros seleccionados.
- Solo los integrantes de "Administración CINTAC" y los superusuarios pueden crear, editar o eliminar tarifas. Los superusuarios conservan el acceso de respaldo.
- Inicio de sesión: /accounts/login/
- Tras tres intentos fallidos de contraseña, el inicio de sesión bloquea esa sesión durante 10 segundos y muestra una cuenta regresiva.
- Cierre de sesión: botón "Cerrar sesión" dentro del cotizador. Las vistas protegidas no se guardan en caché; al usar Atrás después de salir, se solicita el inicio de sesión nuevamente.
- El enlace "Mi perfil", al pie de la barra lateral, permite actualizar nombre, apellidos, correo, RUT opcional y foto de perfil. Las imágenes deben ser válidas y pesar hasta 5 MB.
- Las fotos se guardan en mi_proyecto/media/profile_photos; ejecuta las migraciones para habilitar el perfil. En producción, configura el servidor web para servir MEDIA_ROOT bajo MEDIA_URL.

Vinculación de tarifas con Excel
--------------------------------
- En Administración > Tarifas usa "Vincular Excel de tarifas" para cargar el .xlsx.
- El libro adjunto contiene 14 tarifas de importación.
- Importaciones se valida antes de modificar la base de datos y se procesa en una transacción.
- Las rutas se vinculan por país y puerto de origen; las tarifas generales existentes se actualizan sin duplicarse.
- Los montos se guardan en USD, confirmado para este archivo.
- Solo se admiten importaciones marítimas con las columnas y los valores unitarios esperados.
- El total almacenado en el Excel debe coincidir con cantidad × valor unitario; guarda/recalcula el libro antes de cargarlo.
- La carga procesa la hoja Importaciones y no requiere hojas adicionales.
- Otras rutas, tarifas de destino y referencias existentes no se eliminan ni se alteran.
- Cada tarifa importada conserva el nombre del archivo y número de fila como referencia verificable.
- El archivo no se sincroniza automáticamente desde Descargas: vuelve a cargar la versión actualizada para aplicar cambios.

Vista de tarifas
----------------
- La opción "Tarifas" abre /tarifas/ para consultar los antecedentes almacenados.
- Incluye búsqueda por país, origen, destino, embarcador, tipo de ruta o fuente; los resultados están paginados.
- Muestra rangos de precio, moneda, tránsito, fuente y última actualización.
- Requiere iniciar sesión; es una vista de consulta y la edición/importación sigue en Administración.

Comparación de alternativas
---------------------------
- Compara otras tarifas del mismo origen que aplican al destino cotizado, incluidas las tarifas generales sin destino específico; excluye la tarifa seleccionada.
- Para la cantidad y tamaño de contenedor recomendados, muestra rango unitario, total estimado, tránsito con margen, tipo de ruta, embarcador y fuente.
- Convierte los totales a la moneda de cotización para que se puedan comparar aunque las tarifas estén registradas en CLP o USD; conserva la moneda original en la tarifa unitaria.
- La descarga Excel incluye los mismos datos de las alternativas.
- Los antecedentes compartidos no identifican tres embarcadores para cada ruta. Registra cada tarifa y su fuente en Administración para que aparezca en la comparación; no se inventan precios ni proveedores faltantes.

Conversión e historial de cotizaciones
--------------------------------------
- Al cotizar, el usuario puede elegir la moneda desde la que convertir: CLP se convierte a USD y USD se convierte a CLP.
- El tipo de cambio se ingresa como CLP por USD; para pasar de CLP a USD se divide y para pasar de USD a CLP se multiplica.
- Si la moneda elegida difiere de la moneda de la tarifa guardada, primero se calcula su equivalente para luego aplicar la conversión solicitada.
- La cotización muestra el monto en la moneda elegida, el equivalente convertido y la moneda y montos originales de la tarifa.
- Cada cotización válida queda guardada con la ruta, carga, montos original, base y convertido, moneda, tipo de cambio y tránsito calculados.
- La opción "Historial" abre /historial/ y muestra las cotizaciones del usuario autenticado, con paginación.
- El historial conserva una copia de los datos cotizados aunque la tarifa de origen se edite o elimine.
- Cada cotización del historial tiene una vista de detalle con el desglose de contenedores y alternativas guardadas al momento del cálculo.

Registro de importaciones
-------------------------
- El cotizador y el administrador solo gestionan tarifas de importación.
- Los administradores pueden cargar tarifas manualmente desde Tarifas > Cargar tarifa y eliminarlas con confirmación.
- Los administradores pueden editar cada tarifa existente desde la lista de Tarifas.
- Todos los campos del alta/edición usan menús de selección; el embarcador se limita a los ya registrados y no permite agregar nombres nuevos desde este formulario. Los fletes USD van de 0 a 20.000 en pasos de 50, CLP de 0 a 20.000.000 en pasos de 10.000 y el tránsito de 1 a 120 días.
- Los selectores de origen, destino, embarcador, tipo de ruta y referencia muestran opciones del catálogo y de las tarifas de importación existentes.
- Las tarifas con origen en Chile y las cotizaciones relacionadas se eliminan al migrar a una operación solo de importación.
- Los usuarios registrados consultan y cotizan únicamente tarifas de importación.
- La importación del Excel procesa la hoja Importaciones y no requiere hojas adicionales.

Inicio local en otro equipo
---------------------------
Instala Python 3.12 o superior. En Windows, usa el lanzador `py` para elegir
una versión instalada, aunque `python` no esté en PATH o Windows intente abrir
Microsoft Store. `py -0p` muestra las versiones disponibles. Usa un entorno
virtual para instalar las dependencias del proyecto sin modificar la
instalación de Python del equipo.

No copies `.venv` de otro equipo: el entorno virtual guarda la ruta de la
instalación de Python que lo creó y deja de funcionar si esa ruta no existe.

Desde la carpeta mi_proyecto, la primera vez en cada equipo:
   Windows (PowerShell):
      py -3 -m venv .venv
      .\.venv\Scripts\Activate.ps1
      python -m pip install -r ..\requirements.txt
      python manage.py migrate
      python manage.py runserver
   macOS/Linux:
      python3 -m venv .venv
      source .venv/bin/activate
      python -m pip install -r ../requirements.txt
      python manage.py migrate
      python manage.py runserver

Si el entorno ya existe y aparece un error indicando que no encuentra
`python.exe`, recréalo desde `mi_proyecto` en PowerShell. Esto elimina solo el
entorno virtual y sus paquetes; no elimina la base de datos ni los archivos
del proyecto:
      deactivate
      Remove-Item -Recurse -Force .venv
      py -3 -m venv .venv
      .\.venv\Scripts\Activate.ps1
      python -m pip install -r ..\requirements.txt

Para iniciar el proyecto en ocasiones posteriores, abre una terminal y
activa el entorno virtual desde la carpeta mi_proyecto:
   Windows (PowerShell), desde la carpeta raíz del proyecto:
      cd .\mi_proyecto
      .\.venv\Scripts\Activate.ps1
      python manage.py runserver
   macOS/Linux, desde la carpeta raíz del proyecto:
      cd mi_proyecto
      source .venv/bin/activate
      python manage.py runserver

Cuando veas `(.venv)` al inicio de la línea, el entorno está activo. Para
salir del entorno al terminar, ejecuta `deactivate`.

En Windows, si PowerShell bloquea la activación del entorno, ejecuta el
servidor directamente con `.\.venv\Scripts\python.exe manage.py runserver`.
Instala Python y crea el entorno virtual en cada computador.

Para conservar tarifas, usuarios e historial al mover el proyecto, incluye el
archivo mi_proyecto/db.sqlite3 en el comprimido. No lo reemplaces por una base
vacia si necesitas esos datos. La primera instalacion de dependencias requiere
conexion a Internet.