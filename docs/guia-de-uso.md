# Guía de uso

Esta guía te lleva desde cero hasta tu primer reporte, sin poner en riesgo tu cuenta. Toma unos 15 minutos.

- [1. Antes de empezar](#1-antes-de-empezar)
- [2. Crea un acceso de solo lectura](#2-crea-un-acceso-de-solo-lectura)
- [3. Instala los scripts](#3-instala-los-scripts)
- [4. Verifica el acceso](#4-verifica-el-acceso)
- [5. Ejecuta tu primer reporte](#5-ejecuta-tu-primer-reporte)
- [6. Lee el resultado](#6-lee-el-resultado)
- [7. Antes de aplicar un comando sugerido](#7-antes-de-aplicar-un-comando-sugerido)
- [8. Errores comunes](#8-errores-comunes)
- [9. Preguntas frecuentes](#9-preguntas-frecuentes)

## 1. Antes de empezar

Necesitas:

- Python 3.11 o superior (`python3 --version`).
- Acceso a la cuenta AWS que quieres revisar, con permisos para crear una política y un rol en IAM. Solo se necesitan una vez, para el paso 2.
- AWS CLI (opcional, pero recomendado): sirve para verificar el acceso y para ejecutar los comandos sugeridos si decides aplicarlos.

Qué hacen y qué no hacen los scripts:

- Leen la configuración de tus recursos con llamadas `Describe*`, `Get*` y `List*`.
- No crean, modifican ni borran nada. Los comandos que sugieren solo se imprimen en pantalla.
- No envían datos a ningún sitio distinto de AWS. Todo se ejecuta en tu máquina.

## 2. Crea un acceso de solo lectura

Usa un acceso que tenga **solo** la política de este repositorio, aunque tengas otro perfil con más permisos. Así, aunque algo saliera mal, el script no podría cambiar nada. Evita usar el usuario root y las llaves de acceso de larga duración.

Elige una opción.

### Opción A: AWS IAM Identity Center (si tu organización ya lo usa)

1. En la consola de IAM Identity Center, crea un *permission set* llamado `aws-desperdicios-solo-lectura`.
2. Agrégale una política en línea (*inline policy*) con el contenido de `iam/politica-minima.json`.
3. Asígnalo a tu usuario en la cuenta que quieres revisar.
4. En tu máquina, configura el perfil:

   ```bash
   aws configure sso --profile desperdicios
   ```

### Opción B: un rol IAM que asumes desde tu perfil actual

1. Desde la carpeta del repositorio, crea la política (cambia `123456789012` por el ID de tu cuenta en todos los comandos):

   ```bash
   aws iam create-policy \
     --policy-name aws-desperdicios-solo-lectura \
     --policy-document file://iam/politica-minima.json
   ```

2. Crea un archivo `confianza.json`. Permite que las identidades de tu cuenta con permiso `sts:AssumeRole` asuman el rol:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": { "AWS": "arn:aws:iam::123456789012:root" },
         "Action": "sts:AssumeRole"
       }
     ]
   }
   ```

3. Crea el rol y adjúntale la política:

   ```bash
   aws iam create-role \
     --role-name aws-desperdicios-solo-lectura \
     --assume-role-policy-document file://confianza.json

   aws iam attach-role-policy \
     --role-name aws-desperdicios-solo-lectura \
     --policy-arn arn:aws:iam::123456789012:policy/aws-desperdicios-solo-lectura
   ```

4. Agrega el perfil a `~/.aws/config`, donde `source_profile` es el perfil que ya usas:

   ```ini
   [profile desperdicios]
   role_arn = arn:aws:iam::123456789012:role/aws-desperdicios-solo-lectura
   source_profile = default
   ```

Estos comandos de IAM los ejecutas tú, una sola vez. Los scripts de este repositorio nunca escriben en IAM.

## 3. Instala los scripts

```bash
git clone https://github.com/diegotrujillor/aws-desperdicios.git
cd aws-desperdicios
python3 -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Verifica el acceso

```bash
aws sts get-caller-identity --profile desperdicios
```

Debe mostrar el ID de la cuenta correcta y el ARN del rol `aws-desperdicios-solo-lectura`. Si muestra otra cuenta, detente y revisa el perfil antes de seguir.

## 5. Ejecuta tu primer reporte

Empieza por una sola región para ver el formato:

```bash
python scripts/01_gp2_a_gp3.py --profile desperdicios --region us-east-1
```

Luego revisa todas las regiones habilitadas en la cuenta (tarda más):

```bash
python scripts/01_gp2_a_gp3.py --profile desperdicios
```

Para guardar el resultado y procesarlo después:

```bash
python scripts/01_gp2_a_gp3.py --profile desperdicios --json > gp2-a-gp3.json
```

`--help` muestra todas las opciones de cada script.

## 6. Lee el resultado

El reporte tiene estas partes:

| Parte | Qué significa |
|---|---|
| Tabla | Un recurso por fila: región, ID, detalle, ahorro mensual estimado en USD y tipo de ahorro. |
| Ahorro `sin precio` | No se encontró el precio para esa región. El recurso se reporta, pero no suma al total. |
| Tipo `exacto` | El ahorro se calculó con datos completos y precios públicos. |
| Tipo `máximo` | Es un tope. El ahorro real puede ser menor; la sección *Notas* explica por qué. |
| Total estimado | La suma de los ahorros con precio. Son precios on-demand de lista, sin descuentos ni impuestos. |
| Comandos sugeridos | Lo que podrías ejecutar para corregir cada hallazgo. **No se ejecutaron.** |
| Errores | Regiones que no se pudieron revisar y por qué; por ejemplo, un permiso faltante. |
| Notas | Supuestos del cálculo y advertencias específicas del desperdicio. |
| Fuentes de precios | De dónde salió cada precio: la AWS Pricing API o la tabla local, con su fecha. |

## 7. Antes de aplicar un comando sugerido

Los comandos sugeridos sí modifican recursos, así que necesitan un perfil con más permisos que el de solo lectura. Antes de ejecutar cualquiera:

1. Confirma la cuenta, la región y el ID del recurso.
2. Lee las notas del reporte para ese desperdicio.
3. Si el recurso es de producción, hazlo en una ventana de cambios y con un snapshot reciente como respaldo.
4. Aplica el cambio a un solo recurso, verifica el resultado y luego sigue con los demás.

Para `scripts/01_gp2_a_gp3.py` en particular:

- `modify-volume` cambia el volumen en caliente; la instancia sigue funcionando.
- Puedes seguir el avance con:

  ```bash
  aws ec2 describe-volumes-modifications --volume-ids vol-xxxxxxxx --region us-east-1
  ```

  El estado pasa por `modifying` y `optimizing` hasta `completed`.
- Después de modificar un volumen debes esperar al menos 6 horas para volver a modificarlo.

## 8. Errores comunes

| Mensaje | Causa | Solución |
|---|---|---|
| `Falta el permiso IAM 'ec2:DescribeVolumes'.` | El perfil no tiene ese permiso. | Revisa que la política adjunta sea la versión actual de `iam/politica-minima.json`. |
| `No existe el perfil 'X' en tu configuración de AWS CLI` | El nombre de `--profile` no está en `~/.aws/config`. | Revisa el nombre con `aws configure list-profiles`. |
| `No se encontraron credenciales de AWS.` | No hay credenciales activas. | Usa `--profile`, o inicia sesión con `aws sso login --profile desperdicios`. |
| `No se usó la AWS Pricing API: falta el permiso IAM 'pricing:GetProducts'.` | La política no incluye ese permiso. | Es opcional: el script usa la tabla local. Agrégalo si quieres precios de todas las regiones. |
| `Sin precio para la región X` | La Pricing API no estaba disponible y la tabla local no tiene esa región. | Da el permiso `pricing:GetProducts`. |
| `No fue posible conectarse a AWS` | Problema de red o de proxy. | Revisa tu conexión y las variables `HTTPS_PROXY`. |
| Código de salida `1` | Alguna región falló; las demás sí se revisaron. | Lee la sección *Errores* del reporte. |

## 9. Preguntas frecuentes

**¿Ejecutar los scripts modifica algo en mi cuenta?**
No. Solo leen. La política mínima tampoco permitiría escribir.

**¿Por qué el ahorro no coincide con mi factura?**
Los scripts usan precios on-demand de lista. Si tienes Savings Plans, Reserved Instances, descuentos por volumen o créditos, tu ahorro real puede ser menor.

**¿Revisa regiones que no tengo habilitadas?**
No. Sin `--region`, revisa solo las regiones habilitadas en la cuenta.

**Tengo varias cuentas en AWS Organizations. ¿Cómo las reviso?**
Cada ejecución revisa una cuenta. Crea un perfil por cuenta y ejecútalo en un ciclo:

```bash
for perfil in cuenta-dev cuenta-prod; do
  python scripts/01_gp2_a_gp3.py --profile "$perfil" --json > "gp2-$perfil.json"
done
```

**¿Puedo verificar los precios de la tabla local?**
Sí. `config/precios.toml` indica, para cada precio, la URL del archivo público del AWS Price List, su fecha de publicación y el `usagetype` que debes buscar en ese archivo.
