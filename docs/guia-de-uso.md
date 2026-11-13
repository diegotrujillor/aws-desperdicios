# Guía paso a paso

Esta guía es para cualquier persona, aunque nunca haya usado una terminal. Si sigues los pasos en orden, en unos 30 minutos tendrás un reporte de cuánto dinero se está perdiendo en tu cuenta de AWS.

> **Tranquilo: esto no cambia nada en tu cuenta.** Los scripts solo *miran*. No apagan, no borran y no modifican ningún recurso. Además, el permiso que vas a crear en el paso 6 solo deja leer: aunque quisieran, no podrían cambiar nada.

## Índice

- [Antes de empezar](#antes-de-empezar)
- [Paso 1: Abre la terminal](#paso-1-abre-la-terminal)
- [Paso 2: Revisa que tienes Python](#paso-2-revisa-que-tienes-python)
- [Paso 3: Instala AWS CLI](#paso-3-instala-aws-cli)
- [Paso 4: Descarga los scripts](#paso-4-descarga-los-scripts)
- [Paso 5: Prepara los scripts](#paso-5-prepara-los-scripts)
- [Paso 6: Crea un acceso de solo lectura](#paso-6-crea-un-acceso-de-solo-lectura)
- [Paso 7: Comprueba que el acceso funciona](#paso-7-comprueba-que-el-acceso-funciona)
- [Paso 8: Ejecuta tu primer reporte](#paso-8-ejecuta-tu-primer-reporte)
- [Paso 9: Ejecuta los cinco reportes](#paso-9-ejecuta-los-cinco-reportes)
- [Paso 10: Entiende el reporte](#paso-10-entiende-el-reporte)
- [Paso 11: Decide qué hacer](#paso-11-decide-qué-hacer)
- [Paso 12: Limpia al terminar](#paso-12-limpia-al-terminar)
- [Si algo sale mal](#si-algo-sale-mal)
- [Preguntas frecuentes](#preguntas-frecuentes)
- [Palabras que vas a ver](#palabras-que-vas-a-ver)

## Antes de empezar

Necesitas:

- [ ] Un computador con Mac, Windows o Linux.
- [ ] Poder entrar a la consola web de AWS (https://console.aws.amazon.com) de la cuenta que quieres revisar, con permiso para crear usuarios y políticas en IAM. Si no lo tienes, pídele a quien administra la cuenta que haga contigo el [paso 6](#paso-6-crea-un-acceso-de-solo-lectura).
- [ ] Unos 30 minutos.

Cómo leer esta guía:

- Lo que está en un recuadro gris como este es un **comando**: lo copias, lo pegas en la terminal y presionas Enter.

  ```bash
  python3 --version
  ```

- Después de cada comando te digo **qué deberías ver**. Si ves algo distinto, ve a [Si algo sale mal](#si-algo-sale-mal).

## Paso 1: Abre la terminal

La terminal es una ventana donde escribes instrucciones para el computador.

- **Mac:** presiona `Cmd + Espacio`, escribe `Terminal` y presiona Enter.
- **Windows:** presiona la tecla Windows, escribe `PowerShell` y presiona Enter.
- **Linux:** presiona `Ctrl + Alt + T`.

Deja esa ventana abierta durante toda la guía.

## Paso 2: Revisa que tienes Python

Python es el lenguaje en que están escritos los scripts.

Mac o Linux:

```bash
python3 --version
```

Windows:

```powershell
py --version
```

**Deberías ver** algo como `Python 3.12.4`. El número del medio tiene que ser **11 o mayor** (3.11, 3.12, 3.13...).

**Si dice "command not found" o el número es menor:** descarga Python desde https://www.python.org/downloads/, instálalo y vuelve a intentarlo. En Windows, durante la instalación marca la casilla **"Add python.exe to PATH"**. Cierra y vuelve a abrir la terminal después de instalar.

## Paso 3: Instala AWS CLI

AWS CLI es la herramienta oficial de AWS para la terminal. La vas a usar para guardar tu acceso de forma segura.

1. Sigue las instrucciones para tu sistema en la página oficial: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
2. Cierra y vuelve a abrir la terminal.
3. Comprueba que quedó instalada:

   ```bash
   aws --version
   ```

**Deberías ver** algo como `aws-cli/2.x.x Python/3.x ...`.

## Paso 4: Descarga los scripts

**Opción fácil, sin comandos:**

1. Abre https://github.com/diegotrujillor/aws-desperdicios
2. Haz clic en el botón verde **Code** y luego en **Download ZIP**.
3. Descomprime el archivo. Te queda una carpeta llamada `aws-desperdicios-main`.
4. En la terminal, entra a esa carpeta. Si quedó en Descargas:

   Mac o Linux:

   ```bash
   cd ~/Downloads/aws-desperdicios-main
   ```

   Windows:

   ```powershell
   cd $HOME\Downloads\aws-desperdicios-main
   ```

**Opción con git** (si ya lo usas):

```bash
git clone https://github.com/diegotrujillor/aws-desperdicios.git
cd aws-desperdicios
```

**Para comprobar que estás en la carpeta correcta**, escribe `ls` (Mac/Linux) o `dir` (Windows). **Deberías ver** `README.md`, `scripts`, `iam` y otras carpetas.

## Paso 5: Prepara los scripts

Esto crea un espacio aislado para los scripts e instala lo único que necesitan (la librería `boto3` de AWS). Se hace una sola vez.

Mac o Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Deberías ver** que al inicio de la línea de la terminal aparece `(.venv)`, y al final del último comando un mensaje como `Successfully installed boto3...`.

> **Importante:** cada vez que abras una terminal nueva para usar los scripts, entra a la carpeta y vuelve a ejecutar solo la segunda línea (`source .venv/bin/activate` o `.venv\Scripts\activate`).

## Paso 6: Crea un acceso de solo lectura

Vas a crear un "usuario" en AWS que **solo puede mirar**. Así los scripts no tienen forma de cambiar nada.

> Si tu empresa entra a AWS con un portal de inicio de sesión único (AWS IAM Identity Center o "SSO"), sáltate este paso y lee [Mi empresa usa SSO](#mi-empresa-usa-sso-iam-identity-center).

### 6.1 Crea la política (la lista de permisos)

1. Entra a https://console.aws.amazon.com y busca **IAM** en la barra de búsqueda de arriba.
2. En el menú de la izquierda, haz clic en **Políticas** (*Policies*).
3. Haz clic en **Crear política** (*Create policy*).
4. Haz clic en la pestaña **JSON**.
5. Borra todo el texto que aparece.
6. Abre el archivo `iam/politica-minima.json` de la carpeta que descargaste (con el Bloc de notas o TextEdit), copia **todo** su contenido y pégalo en el editor.
7. Haz clic en **Siguiente** (*Next*).
8. En **Nombre de la política** (*Policy name*) escribe `aws-desperdicios-solo-lectura`.
9. Haz clic en **Crear política** (*Create policy*).

### 6.2 Crea el usuario

1. En el menú de la izquierda de IAM, haz clic en **Usuarios** (*Users*) y luego en **Crear usuario** (*Create user*).
2. En **Nombre de usuario** escribe `aws-desperdicios`. **No** marques la opción de acceso a la consola. Haz clic en **Siguiente**.
3. Elige **Adjuntar políticas directamente** (*Attach policies directly*).
4. En el buscador escribe `aws-desperdicios-solo-lectura` y marca la casilla de esa política.
5. Haz clic en **Siguiente** y luego en **Crear usuario**.

### 6.3 Crea la clave de acceso

1. En la lista de usuarios, haz clic en `aws-desperdicios`.
2. Abre la pestaña **Credenciales de seguridad** (*Security credentials*).
3. Baja hasta **Claves de acceso** (*Access keys*) y haz clic en **Crear clave de acceso** (*Create access key*).
4. Elige **Interfaz de línea de comandos (CLI)**, marca la casilla de confirmación y haz clic en **Siguiente** y luego en **Crear clave de acceso**.
5. Vas a ver dos valores: **ID de clave de acceso** y **Clave de acceso secreta**. **No cierres esa pantalla todavía.**

> La clave secreta solo se muestra una vez. No la mandes por correo ni chat y no la guardes en un documento. En el [paso 12](#paso-12-limpia-al-terminar) la vas a borrar.

### 6.4 Guarda la clave en tu computador

En la terminal escribe:

```bash
aws configure --profile desperdicios
```

Te va a hacer cuatro preguntas. Responde así y presiona Enter después de cada una:

| Pregunta | Qué escribir |
|---|---|
| `AWS Access Key ID` | El **ID de clave de acceso** de la pantalla anterior. |
| `AWS Secret Access Key` | La **clave de acceso secreta**. |
| `Default region name` | `us-east-1` (o la región donde tienes más recursos). |
| `Default output format` | `json` |

Listo: ya puedes cerrar la pantalla de la clave en AWS. `desperdicios` es el nombre de tu perfil; lo vas a usar en los comandos.

## Paso 7: Comprueba que el acceso funciona

```bash
aws sts get-caller-identity --profile desperdicios
```

**Deberías ver** algo así:

```json
{
    "UserId": "AIDA...",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/aws-desperdicios"
}
```

Revisa que `Account` sea el número de la cuenta que quieres revisar y que `Arn` termine en `user/aws-desperdicios`. Si no coincide, detente y revisa el paso 6.

## Paso 8: Ejecuta tu primer reporte

Empieza con una sola región para que sea rápido.

Mac o Linux:

```bash
python scripts/01_gp2_a_gp3.py --profile desperdicios --region us-east-1
```

Windows:

```powershell
python scripts\01_gp2_a_gp3.py --profile desperdicios --region us-east-1
```

**Deberías ver** un título, una tabla (o el mensaje *No se encontraron recursos...*) y unas notas al final. Tarda unos segundos.

Si no pones `--region`, el script revisa **todas** las regiones activas de tu cuenta. Es lo recomendable, pero tarda más (uno o dos minutos).

## Paso 9: Ejecuta los cinco reportes

Cada script busca un desperdicio distinto:

| Script | Qué busca, en palabras simples |
|---|---|
| `scripts/01_gp2_a_gp3.py` | Discos de un tipo viejo (gp2) que cuestan más que el tipo nuevo (gp3) y rinden igual o menos. |
| `scripts/02_volumenes_y_snapshots.py` | Discos que no están conectados a ningún servidor y copias de respaldo (snapshots) viejas. |
| `scripts/03_entornos_dev_24x7.py` | Servidores y bases de datos de desarrollo o pruebas que están prendidos de noche y los fines de semana. |
| `scripts/04_logs_sin_retencion.py` | Registros (logs) que se guardan para siempre porque nadie les puso fecha de vencimiento. |
| `scripts/05_nat_sin_endpoints.py` | Tráfico hacia S3 o DynamoDB que pasa por un NAT Gateway (se cobra por GB) en vez de una ruta gratuita. |

Ejecuta cada uno igual que en el paso 8, cambiando el nombre del script. Para guardar los cinco resultados en archivos, en Mac o Linux:

```bash
for script in scripts/0*.py; do
  python "$script" --profile desperdicios > "$(basename "$script" .py).txt"
done
```

Quedan cinco archivos `.txt` en la carpeta, uno por desperdicio, que puedes abrir con cualquier editor de texto.

Cada script tiene opciones extra (por ejemplo, cuántos días de antigüedad o qué horario de trabajo suponer). Para verlas, agrega `--help`:

```bash
python scripts/03_entornos_dev_24x7.py --help
```

## Paso 10: Entiende el reporte

Este es un ejemplo con datos de prueba:

```text
Desperdicio 1: volúmenes EBS gp2 que podrían ser gp3
====================================================

Región     Recurso                Detalle                                                  Ahorro USD/mes  Tipo
---------  ---------------------  -------------------------------------------------------  --------------  ------
us-east-1  vol-6a3167a266a789ee3  100 GiB gp2, sin adjuntar -> gp3 3000 IOPS / 128 MiB/s   1.88            exacto

Total estimado: 1.88 USD/mes

Comandos sugeridos (no se ejecutaron; revísalos antes de usarlos):
  aws ec2 modify-volume --region us-east-1 --volume-id vol-6a3167a266a789ee3 --volume-type gp3 --iops 3000 --throughput 128

Notas:
  - ...

Fuentes de precios:
  - Tabla local config/precios.toml (AWS Price List publicado 2026-11-10)
```

Qué significa cada parte:

- **Región:** el lugar del mundo donde está el recurso (`us-east-1` es Virginia, `sa-east-1` es São Paulo).
- **Recurso:** el identificador del recurso en AWS. Puedes pegarlo en el buscador de la consola para encontrarlo.
- **Detalle:** qué es y por qué aparece.
- **Ahorro USD/mes:** cuánto dejarías de pagar cada mes si lo corriges. Si dice `sin precio`, el script encontró el recurso pero no el precio, y no lo suma al total.
- **Tipo:**
  - `exacto`: la cifra sale de datos completos de tu cuenta.
  - `máximo`: es un tope. El ahorro real puede ser menor. Las notas explican por qué.
- **Total estimado:** la suma de la columna de ahorro. Usa precios de lista de AWS: si tu empresa tiene descuentos, el ahorro real puede ser menor.
- **Comandos sugeridos:** cómo se corregiría cada hallazgo. **El script no los ejecutó.**
- **Notas:** supuestos y advertencias. Léelas siempre.
- **Fuentes de precios:** de dónde salieron los precios, para que puedas verificarlos.

## Paso 11: Decide qué hacer

El reporte es una lista de oportunidades, no una orden. Antes de cambiar algo:

1. **Pregunta de quién es.** Busca el recurso en la consola de AWS y mira sus etiquetas (*Tags*), como `Name`, `Owner` o `Project`. Confirma con el equipo dueño.
2. **Empieza por lo más grande.** Ordena por la columna de ahorro y revisa primero lo que más cuesta.
3. **Cambia un recurso a la vez** y comprueba que todo sigue funcionando antes de seguir.
4. **Los comandos sugeridos necesitan otro acceso.** El usuario `aws-desperdicios` solo puede leer, así que esos comandos fallarán con él. Los debe ejecutar alguien con permisos de administración.

Cuidados por script:

- `scripts/01_gp2_a_gp3.py`: el cambio de disco se hace sin apagar el servidor. Después de cambiar un disco hay que esperar 6 horas para volver a modificarlo. Puedes ver el avance con `aws ec2 describe-volumes-modifications --volume-ids vol-xxxx --region us-east-1`.
- `scripts/02_volumenes_y_snapshots.py`: **borrar no tiene vuelta atrás.** Si no estás seguro de un disco, crea antes una copia (snapshot), que cuesta menos que el disco. Un snapshot que usa una imagen (AMI) no se puede borrar mientras la imagen exista.
- `scripts/03_entornos_dev_24x7.py`: apagar un servidor cambia su IP pública (salvo que tenga una IP elástica) y borra los discos temporales (*instance store*). Confirma que nadie lo usa de noche: pipelines, pruebas programadas, compañeros en otro huso horario. El comando sugerido apaga una sola vez; para un horario fijo se necesita una automatización, como Amazon EventBridge Scheduler.
- `scripts/04_logs_sin_retencion.py`: poner retención **borra para siempre** los registros más viejos que el plazo. Si alguna norma obliga a guardarlos (auditoría, contratos), expórtalos antes a S3.
- `scripts/05_nat_sin_endpoints.py`: crear la ruta gratuita (endpoint) cambia el camino del tráfico hacia S3 o DynamoDB. Revisa antes si alguna política de bucket filtra por IP (`aws:SourceIp`) o por VPC.

## Paso 12: Limpia al terminar

Cuando ya no vayas a usar los scripts, borra la clave de acceso:

1. En la consola de AWS ve a **IAM → Usuarios → aws-desperdicios → Credenciales de seguridad**.
2. En **Claves de acceso**, abre el menú de **Acciones** de la clave, elige **Desactivar** y luego **Eliminar**.
3. Si no lo vas a volver a usar, borra también el usuario `aws-desperdicios`.

En tu computador, borra el perfil del archivo de credenciales: abre `~/.aws/credentials` (Mac/Linux) o `%USERPROFILE%\.aws\credentials` (Windows) con un editor y elimina el bloque `[desperdicios]`.

## Si algo sale mal

| Ves esto | Qué pasa | Qué hacer |
|---|---|---|
| `command not found: python3` o `py no se reconoce` | Python no está instalado o la terminal no lo encuentra. | Vuelve al [paso 2](#paso-2-revisa-que-tienes-python). Cierra y abre la terminal después de instalar. |
| `No module named 'boto3'` | No activaste el espacio aislado. | Ejecuta `source .venv/bin/activate` (Mac/Linux) o `.venv\Scripts\activate` (Windows). |
| `can't open file ... scripts/01_gp2_a_gp3.py` | La terminal no está en la carpeta de los scripts. | Vuelve al final del [paso 4](#paso-4-descarga-los-scripts). |
| `No existe el perfil 'desperdicios'` | No se guardó el perfil. | Repite el [paso 6.4](#64-guarda-la-clave-en-tu-computador). |
| `No se encontraron credenciales de AWS.` | Olvidaste `--profile desperdicios`. | Agrégalo al final del comando. |
| `Falta el permiso IAM '...'` | A la política le falta ese permiso, o es una versión vieja. | Repite el [paso 6.1](#61-crea-la-política-la-lista-de-permisos) con el `iam/politica-minima.json` actual (edita la política existente y pega el contenido nuevo). |
| `No se usó la AWS Pricing API...` | La política no tiene el permiso de precios. | No es grave: el script usa una tabla de precios incluida. |
| `Sin precio de ... en la región ...` | No hay precio disponible para esa región. | El recurso aparece igual, pero sin cifra de ahorro. |
| `InvalidClientTokenId` o `SignatureDoesNotMatch` | La clave se copió mal o fue borrada. | Crea una clave nueva ([paso 6.3](#63-crea-la-clave-de-acceso)) y repite el [paso 6.4](#64-guarda-la-clave-en-tu-computador). |
| `No fue posible conectarse a AWS` | Problema de internet o de proxy. | Revisa tu conexión. Si estás en una red corporativa, pregunta por el proxy. |

## Preguntas frecuentes

**¿Puede dañar algo?**
No. Los scripts solo leen, y el usuario que creaste solo tiene permisos de lectura.

**¿Cuesta algo ejecutarlos?**
Los scripts 1 a 4 solo hacen consultas de lectura. El script 5 lee métricas de CloudWatch (2 consultas por NAT Gateway), y AWS cobra esas consultas: USD 0.01 por cada 1.000 en us-east-1, según el AWS Price List.

**¿Mis datos salen de mi computador?**
No. El script solo se conecta a AWS con tu clave. No envía nada a ningún otro lugar.

**¿Por qué el ahorro no coincide con mi factura?**
Los scripts usan precios de lista. Si tu empresa tiene Savings Plans, Reserved Instances, descuentos o créditos, el ahorro real puede ser menor.

**¿Revisa todas mis regiones?**
Sí, todas las que están activas en la cuenta, salvo que uses `--region`.

**Tengo varias cuentas de AWS. ¿Cómo las reviso?**
Haz el paso 6 en cada cuenta con un nombre de perfil distinto (por ejemplo `desperdicios-dev` y `desperdicios-prod`) y cambia `--profile` en los comandos.

**¿Puedo verificar los precios?**
Sí. El archivo `config/precios.toml` indica, para cada precio, de qué archivo público de AWS salió y cómo buscarlo.

### Mi empresa usa SSO (IAM Identity Center)

Pídele a quien administra AWS que:

1. Cree un *permission set* llamado `aws-desperdicios-solo-lectura` con una política en línea (*inline policy*) igual al contenido de `iam/politica-minima.json`.
2. Te lo asigne en la cuenta que quieres revisar.

Luego, en la terminal:

```bash
aws configure sso --profile desperdicios
```

Responde con la URL de inicio de sesión de tu empresa y la región que te indiquen. Elige la cuenta y el rol `aws-desperdicios-solo-lectura`. Después sigue desde el [paso 7](#paso-7-comprueba-que-el-acceso-funciona). Cuando la sesión venza, entra de nuevo con `aws sso login --profile desperdicios`.

<details>
<summary>Opción avanzada: un rol IAM en vez de un usuario</summary>

Si ya tienes un perfil de AWS CLI con permisos de administración, puedes evitar las claves de larga duración y crear un rol que asumes desde ese perfil (cambia `123456789012` por el ID de tu cuenta):

```bash
aws iam create-policy --policy-name aws-desperdicios-solo-lectura \
  --policy-document file://iam/politica-minima.json

aws iam create-role --role-name aws-desperdicios-solo-lectura \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::123456789012:root"},"Action":"sts:AssumeRole"}]}'

aws iam attach-role-policy --role-name aws-desperdicios-solo-lectura \
  --policy-arn arn:aws:iam::123456789012:policy/aws-desperdicios-solo-lectura
```

Y agrega a `~/.aws/config`:

```ini
[profile desperdicios]
role_arn = arn:aws:iam::123456789012:role/aws-desperdicios-solo-lectura
source_profile = default
```

</details>

## Palabras que vas a ver

| Palabra | Qué es |
|---|---|
| **AWS CLI** | Programa oficial de AWS para usar AWS desde la terminal. |
| **IAM** | La parte de AWS donde se crean usuarios y se deciden sus permisos. |
| **Política** | Lista de permisos: qué puede hacer un usuario. |
| **Perfil** | Un nombre (aquí, `desperdicios`) con el que tu computador recuerda qué clave usar. |
| **Región** | Centro de datos de AWS en una zona del mundo (`us-east-1`, `sa-east-1`...). |
| **EBS / volumen** | Disco de un servidor en AWS. |
| **Snapshot** | Copia de respaldo de un disco. |
| **EC2** | Servidor virtual en AWS. |
| **RDS** | Base de datos administrada por AWS. |
| **CloudWatch Logs** | Donde AWS guarda los registros (logs) de aplicaciones y servicios. |
| **NAT Gateway** | Puerta de salida a internet para servidores privados. Cobra por hora y por cada GB que pasa. |
| **Endpoint gateway** | Ruta privada y gratuita hacia S3 o DynamoDB, sin pasar por el NAT. |
