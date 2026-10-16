# TuBiblia para Linux/Windows

TuBiblia es una aplicación de escritorio local para leer módulos bíblicos de
MyBible. Permite importar un módulo SQLite existente o buscar y descargar
módulos publicados en el catálogo oficial de MyBible.

## Funciones de esta primera versión

- Importar módulos bíblicos SQLite de MyBible (`.SQLite3`).
- Consultar el catálogo oficial de MyBible y descargar el módulo seleccionado
  mediante HTTPS, con confirmación antes de iniciar la descarga.
- Leer libros y capítulos del módulo instalado.
- Navegar por los libros y capítulos y abrir una referencia desde los
  resultados de búsqueda.
- Buscar palabras o frases sin distinguir mayúsculas/minúsculas, preservando
  las tildes.
- Guardar los módulos importados y la última posición de lectura localmente.
- Mostrar el logo de TuBiblia y un fondo de color pergamino sólido, con texto
  negro.
- Comparar lado a lado dos traducciones instaladas, alineadas por referencia,
  indicando claramente los versículos que falten en cada módulo.
- Elegir entre apariencia pergamino, clara y oscura, con preferencia guardada.
- Seleccionar y preparar perfiles de idioma y voz de Pocket TTS desde el menú
  **Voces**: inglés (`alba`), francés (`estelle`), alemán (`juergen`), italiano
  (`giovanni`), neerlandés (`daan`), portugués (`rafael`) y español (`lola`).

No se incluye ni se redistribuye ningún texto bíblico. La descarga requiere
Internet; una vez instalado un módulo, la lectura funciona sin conexión.
Antes de descargar, importar o utilizar un módulo, comprueba sus condiciones
de licencia y los avisos de derechos mostrados por el catálogo. La presencia
de un módulo en el catálogo no concede derechos de redistribución. El módulo
RVR observado en el registro no contiene metadatos suficientes para afirmar
que pueda redistribuirse.

## Lectura en voz alta

Pocket TTS es una dependencia de la aplicación y genera el audio en segundo plano.
TuBiblia ofrece los perfiles de idioma/voz predefinidos que actualmente expone
Pocket TTS: `english`/`alba`, `french`/`estelle`, `german`/`juergen`,
`italian`/`giovanni`, `dutch`/`daan`, `portuguese`/`rafael` y
`spanish`/`lola`. No se ofrecen voces fuera de ese catálogo. La barra de lectura
divide el capítulo por versículos, comienza a reproducir el primer segmento
mientras sintetiza los siguientes y conserva como máximo un segmento listo por
delante. La barra dedicada de lectura ofrece reproducir/pausar (▶/Ⅱ), detener
(■), acceso a la selección de voz, velocidad ajustable entre 0,5× y 2,0×,
estado y progreso por versículo. La velocidad se guarda en las preferencias y
se aplica también a los segmentos que aún se están generando. Al terminar un
capítulo, la lectura pasa al capítulo siguiente disponible.

Para Ubuntu/Linux, instala primero una compilación CPU de PyTorch y luego el
extra:

```bash
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e .
```

La primera carga del modelo y de la voz puede requerir Internet, acceso a los
recursos de Kyutai y aceptación de sus condiciones. Una vez descargados y
almacenados en caché, Pocket TTS puede generar audio localmente sin conexión.
Las condiciones de uso de voces y muestras se publican en el
[catálogo oficial de voces](https://huggingface.co/kyutai/tts-voices); TuBiblia
no redistribuye modelos ni muestras de voz. Comprueba las condiciones vigentes
antes de usar o redistribuir esos recursos.

El motor se instala junto con TuBiblia. La primera preparación de la voz carga
el modelo y los recursos de Kyutai en la caché local, por lo que puede requerir
Internet; no es necesario instalarlos con un comando separado. La reproducción
real todavía requiere una prueba en un equipo que tenga disponibles los
recursos de Pocket TTS y un dispositivo de audio.

## Requisitos

- Ubuntu o Linux de escritorio.
- Python 3.10 o posterior.
- PySide6 (instalado desde `pyproject.toml`).
- PyTorch CPU y Pocket TTS (dependencias del proyecto).

## Instalar y ejecutar desde el código fuente

```bash
cd mybible-linux
python3 -m venv .venv
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m tubiblia
```

Pocket TTS se instala como dependencia del proyecto. PyTorch CPU se instala
explícitamente para evitar descargar una compilación CUDA innecesaria. La
primera carga del modelo/voz desde el menú **Voces** puede requerir Internet y
aceptar las condiciones de los recursos; consulta [Lectura en voz
alta](#lectura-en-voz-alta) para más detalles.

## Crear el AppImage para Linux

El script crea un AppImage x86_64 con TuBiblia, Qt y Pocket TTS. Usa un entorno
de compilación separado e instala la versión CPU de PyTorch, sin alterar el
entorno virtual de desarrollo. El archivo final puede ser grande; los modelos
y las voces de Pocket TTS no se incluyen y se descargan desde la aplicación al
preparar una voz. Se necesita `appimagetool` instalado o descargado desde sus
[releases oficiales](https://github.com/AppImage/appimagetool/releases).

```bash
mkdir -p build/appimage/tools
curl -fL -o build/appimage/tools/appimagetool-x86_64.AppImage \
  https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x build/appimage/tools/appimagetool-x86_64.AppImage
chmod +x packaging/build-appimage.sh
packaging/build-appimage.sh
```

El resultado se guarda en `dist/TuBiblia-x86_64.AppImage`. Para ejecutarlo:

```bash
chmod +x dist/TuBiblia-x86_64.AppImage
./dist/TuBiblia-x86_64.AppImage
```

El AppImage se construye para x86_64 en la distribución Linux donde se compila;
su compatibilidad con otras distribuciones no se ha certificado. La ejecución
normal requiere FUSE; en equipos sin FUSE se puede usar el modo de extracción
incluido en AppImage con `--appimage-extract-and-run`.

## Crear el instalador para Windows 11

El instalador x64 debe compilarse en Windows con Python 3.12 e Inno Setup 6.
Desde PowerShell, en la carpeta del proyecto:

```powershell
.\packaging\windows\build-installer.ps1
```

El proceso crea `dist\TuBiblia-Setup-x64.exe`, con PyTorch CPU, Pocket TTS,
Qt y el icono de TuBiblia. No incluye módulos bíblicos ni modelos/voces. También
se puede ejecutar el flujo **Windows installer** de GitHub Actions para obtener
el instalador como artefacto. Esta configuración está preparada, pero el `.exe`
de Windows no se ha compilado ni probado desde este equipo Linux.

En el primer inicio, elige **Descargar módulos** para consultar el catálogo
oficial de MyBible o **Importar módulo** para seleccionar un módulo SQLite
(`.SQLite3`) que ya tengas. TuBiblia verifica las tablas requeridas y guarda
el módulo en su directorio local de datos.

Los módulos se guardan bajo `QStandardPaths.AppDataLocation` de Qt y los datos
de navegación en la configuración local de Qt. La aplicación funciona sin
conexión después de importar los módulos.

## Pruebas

```bash
.venv/bin/python -m pytest
```

## Estructura

```text
tubiblia/
  app.py            Punto de entrada de Qt
  assets.py         Acceso a recursos visuales empaquetados
  assets/           Logo y fondo de pergamino
  main_window.py    Interfaz, navegación y búsqueda
  module_catalog.py Cliente HTTPS y parser del catálogo MyBible
  module_catalog_dialog.py  Búsqueda, descarga e instalación desde la interfaz
  module_store.py   Validación, importación y consultas SQLite
  pocket_tts.py     Motor Pocket TTS y generación de WAV
  reading_controller.py  Estados de lectura, generación en segundo plano y reproducción
tests/
  test_module_store.py
  test_main_window.py
  test_pocket_tts.py
```

## Licencia

Copyright © 2026 **CunaWare.Lab**.

TuBiblia se distribuye bajo la licencia [GNU General Public License, versión 3](LICENSE) (GPL-3.0).

Esta licencia permite utilizar, estudiar, modificar y redistribuir el software conforme a sus términos y condiciones. La distribución de copias o versiones modificadas debe cumplir las obligaciones establecidas por la GPL-3.0, incluidos los requisitos aplicables sobre avisos de copyright, licencia y modificaciones.

**La autorización para modificar o redistribuir TuBiblia no concede permiso para atribuirse falsamente la autoría del código original ni para eliminar los avisos de autoría y licencia que deban conservarse.** Las contribuciones y modificaciones propias pueden identificarse por separado, respetando los derechos de los autores originales.

Consulta el archivo [LICENSE](LICENSE) para conocer el texto completo de la licencia.

Las dependencias de terceros conservan sus respectivas licencias y condiciones de uso. Entre ellas se encuentran Pocket TTS, PySide6, PyTorch y los recursos de voz y modelos de Kyutai. Consulta la documentación de cada componente para conocer sus términos específicos.

## Aviso legal sobre MyBible

TuBiblia es un proyecto independiente: no está afiliado, respaldado ni
patrocinado por el proyecto MyBible. «MyBible» es una marca de sus respectivos
titulares y se menciona únicamente para identificar la compatibilidad con el
formato de módulos y su catálogo público. TuBiblia no incluye ni redistribuye
ningún texto bíblico: cada módulo se descarga, a petición del usuario, desde
los servidores oficiales de MyBible, y su uso queda sujeto a las condiciones
de licencia de cada módulo.

## Pendiente

Marcadores, notas, historial detallado, resaltados, preferencias tipográficas
de lectura y exportación/importación de datos personales no forman parte de
este MVP.
