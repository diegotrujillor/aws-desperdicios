# aws-desperdicios

Scripts en Python para detectar desperdicios comunes en cuentas AWS y estimar cuánto cuestan al mes, con precios que se pueden verificar.

> **Solo lectura.** Ningún script crea, modifica ni borra recursos. Solo hacen llamadas `Describe*`, `Get*` y `List*`. Cuando un hallazgo tiene arreglo, el script **imprime** el comando de AWS CLI correspondiente para que tú lo revises y decidas si lo ejecutas. Nunca lo ejecuta.

Si es tu primera vez, empieza por la [guía de uso](docs/guia-de-uso.md): explica paso a paso cómo crear un acceso de solo lectura, ejecutar los scripts e interpretar el resultado.

## Contenido

- [Los desperdicios](#los-desperdicios)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Uso](#uso)
- [Cómo se calcula el ahorro](#cómo-se-calcula-el-ahorro)
- [Política IAM mínima](#política-iam-mínima)
- [Códigos de salida](#códigos-de-salida)
- [Desarrollo y pruebas](#desarrollo-y-pruebas)
- [Licencia](#licencia)

## Los desperdicios

| # | Desperdicio | Script | Tipo de ahorro | Estado |
|---|---|---|---|---|
| 1 | Volúmenes EBS gp2 que podrían ser gp3 | `scripts/01_gp2_a_gp3.py` | exacto | disponible |
| 2 | Volúmenes EBS sin adjuntar y snapshots antiguos | `scripts/02_volumenes_y_snapshots.py` | exacto (volúmenes) y máximo (snapshots) | disponible |
| 3 | Entornos de desarrollo y pruebas encendidos 24/7 | — | exacto (según horario supuesto) | en desarrollo |
| 4 | Grupos de logs de CloudWatch con retención infinita | — | máximo | en desarrollo |
| 5 | NAT Gateway procesando tráfico hacia S3/DynamoDB | — | máximo | en desarrollo |

## Requisitos

- Python 3.11 o superior.
- Credenciales de AWS configuradas (perfil de AWS CLI, AWS IAM Identity Center o variables de entorno).
- Esas credenciales deben tener al menos la [política IAM mínima](#política-iam-mínima) de este repositorio.

No hace falta tener instalado AWS CLI para ejecutar los scripts; solo para usar los comandos sugeridos.

## Instalación

```bash
git clone https://github.com/diegotrujillor/aws-desperdicios.git
cd aws-desperdicios
python3 -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

La única dependencia es `boto3`.

## Uso

Todos los scripts aceptan las mismas opciones:

| Opción | Qué hace | Valor por defecto |
|---|---|---|
| `--profile NOMBRE` | Perfil de AWS CLI a usar. | Cadena estándar de credenciales de AWS. |
| `--region REGION` | Revisa solo esa región. | Todas las regiones habilitadas en la cuenta. |
| `--json` | Imprime el resultado en JSON en lugar de tabla. | Tabla. |
| `--precios-locales` | No consulta la AWS Pricing API; usa solo la tabla local. | Consulta la Pricing API. |
| `--precios RUTA` | Usa otra tabla local de precios. | `config/precios.toml` |
| `--help` | Muestra la ayuda del script. | — |

### 1. Volúmenes EBS gp2 que podrían ser gp3

```bash
python scripts/01_gp2_a_gp3.py --profile mi-perfil
python scripts/01_gp2_a_gp3.py --profile mi-perfil --region sa-east-1 --json
```

**Qué detecta.** Todos los volúmenes EBS de tipo `gp2`, adjuntos o no.

**Por qué es un desperdicio.** gp3 cuesta menos por GB que gp2 (en us-east-1, 0.08 contra 0.10 USD por GB-mes) e incluye 3.000 IOPS y 125 MiB/s sin costo adicional. El cambio se hace en caliente, sin detener la instancia.

**Cómo calcula el ahorro.** Para cada volumen:

1. Calcula el máximo que el gp2 puede entregar según la documentación de AWS: 3 IOPS por GiB (mínimo 100, máximo 16.000) y hasta 128 MiB/s si mide 170 GiB o menos, o hasta 250 MiB/s si mide más.
2. Propone un gp3 que iguala o supera ese máximo, sin bajar de 3.000 IOPS, que es lo que un gp2 pequeño alcanza en ráfaga.
3. Ahorro = costo del gp2 − costo del gp3 propuesto (almacenamiento + IOPS adicionales + throughput adicional).

**Ejemplo de salida** (datos simulados con [moto](https://github.com/getmoto/moto)):

```text
Desperdicio 1: volúmenes EBS gp2 que podrían ser gp3
====================================================

Región     Recurso                Detalle                                                  Ahorro USD/mes  Tipo
---------  ---------------------  -------------------------------------------------------  --------------  ------
us-east-1  vol-6a3167a266a789ee3  100 GiB gp2, sin adjuntar -> gp3 3000 IOPS / 128 MiB/s   1.88            exacto
us-east-1  vol-5edb905c4344b80bd  1000 GiB gp2, sin adjuntar -> gp3 3000 IOPS / 250 MiB/s  15.00           exacto

Total estimado: 16.88 USD/mes

Comandos sugeridos (no se ejecutaron; revísalos antes de usarlos):
  aws ec2 modify-volume --region us-east-1 --volume-id vol-6a3167a266a789ee3 --volume-type gp3 --iops 3000 --throughput 128
  aws ec2 modify-volume --region us-east-1 --volume-id vol-5edb905c4344b80bd --volume-type gp3 --iops 3000 --throughput 250

Notas:
  - El gp3 sugerido iguala o supera el máximo de IOPS y throughput que el gp2 puede entregar (incluida la ráfaga de 3.000 IOPS), así que el rendimiento no baja.
  - El cambio de gp2 a gp3 se hace en caliente con modify-volume, sin detener la instancia; un mismo volumen solo se puede modificar una vez cada 6 horas.
  - Los volúmenes 'sin adjuntar' también aparecen en el script 02: quizá conviene borrarlos en vez de migrarlos.

Fuentes de precios:
  - Tabla local config/precios.toml (AWS Price List publicado 2026-11-10)
```

El cálculo del primer volumen: gp2 100 GiB × 0.10 = 10.00; gp3 100 GiB × 0.08 + 3 MiB/s adicionales × 0.04 = 8.12; ahorro 1.88 USD/mes.

Con `--json`, cada hallazgo tiene esta forma:

```json
{
  "region": "us-east-1",
  "recurso": "vol-7f74f19bd8b858bf0",
  "detalle": "1000 GiB gp2, sin adjuntar -> gp3 3000 IOPS / 250 MiB/s",
  "ahorro_mensual_usd": 15.0,
  "tipo_ahorro": "exacto",
  "comandos_sugeridos": ["aws ec2 modify-volume --region us-east-1 --volume-id vol-7f74f19bd8b858bf0 --volume-type gp3 --iops 3000 --throughput 250"]
}
```

El JSON completo también incluye `titulo`, `total_ahorro_mensual_usd`, `errores`, `notas` y `fuentes_de_precios`.

### 2. Volúmenes EBS sin adjuntar y snapshots antiguos

```bash
python scripts/02_volumenes_y_snapshots.py --profile mi-perfil
python scripts/02_volumenes_y_snapshots.py --profile mi-perfil --dias 180
```

Opción propia:

| Opción | Qué hace | Valor por defecto |
|---|---|---|
| `--dias N` | Reporta solo snapshots creados hace más de N días. | 90 |

**Qué detecta.**

- Volúmenes EBS en estado `available`, es decir, sin adjuntar a ninguna instancia.
- Snapshots EBS propios de la cuenta, en el nivel estándar, con más de `--dias` días.

**Por qué es un desperdicio.** Un volumen sin adjuntar se cobra completo (almacenamiento, IOPS y throughput aprovisionados) aunque nadie lo use. Los snapshots antiguos se acumulan, sobre todo cuando ya se borró el volumen del que salieron.

**Cómo calcula el ahorro.**

- Volúmenes, **exacto**: costo mensual completo del volumen según su tipo. Incluye las IOPS y el throughput adicionales de gp3, las IOPS de io1 y las IOPS por tramos de io2.
- Snapshots, **máximo**: tamaño del volumen de origen × precio del snapshot por GB-mes. Los snapshots son incrementales y las APIs de solo lectura no muestran cuántos bytes factura cada uno, así que el ahorro real es igual o menor.

**Casos especiales.** Los snapshots que usa una AMI propia o que administra AWS Backup se listan sin comando y sin ahorro, con el motivo en el detalle: primero hay que desregistrar la AMI o ajustar el plan de respaldo. El detalle también avisa cuando el volumen de origen ya no existe.

## Cómo se calcula el ahorro

**Tipo de ahorro.** Cada hallazgo indica uno de dos tipos:

- **exacto**: el ahorro se calcula con datos completos de la cuenta y precios públicos.
- **máximo**: las APIs de solo lectura no dan el dato exacto (por ejemplo, cuánto tráfico de un NAT Gateway va a S3). El valor es un tope: el ahorro real es igual o menor. Cada script explica por qué.

**Origen de los precios.** En este orden:

1. **AWS Pricing API** (`pricing:GetProducts`), consultada en el momento. Es la fuente preferida porque está al día y cubre todas las regiones.
2. **Tabla local** `config/precios.toml`, si la API no está disponible (falta el permiso, no hay red o usaste `--precios-locales`). Cada precio indica el archivo público del AWS Price List de donde salió, la fecha de publicación y el `usagetype` para que puedas verificarlo. Hoy cubre us-east-1, us-east-2 y sa-east-1.
3. Si ninguna de las dos tiene el precio, el hallazgo aparece como **sin precio** y no suma al total. Ningún script inventa ni aproxima un precio.

La salida siempre lista las fuentes de precios usadas.

**Lo que el cálculo no incluye.** Los precios son on-demand de lista, en USD y sin impuestos. Si tu organización tiene descuentos (Savings Plans, Reserved Instances, acuerdos privados o créditos), el ahorro real en tu factura puede ser menor.

## Política IAM mínima

Archivo: [`iam/politica-minima.json`](iam/politica-minima.json). Contiene exactamente los permisos que usan los scripts, todos de solo lectura:

| Permiso | Para qué |
|---|---|
| `ec2:DescribeRegions` | Listar las regiones habilitadas (no se usa si pasas `--region`). |
| `ec2:DescribeVolumes` | Scripts 1 y 2: listar volúmenes EBS. |
| `ec2:DescribeSnapshots` | Script 2: listar snapshots propios. |
| `ec2:DescribeImages` | Script 2: saber qué snapshots usa una AMI propia. |
| `pricing:GetProducts` | Consultar precios en la AWS Pricing API. Es opcional: sin él se usa la tabla local. |

Para aplicarla, usa el archivo tal cual; no copies la política desde este README.

Una prueba automática verifica que la política coincida exactamente con las llamadas que hacen los scripts y que todas sean de lectura. La [guía de uso](docs/guia-de-uso.md#2-crea-un-acceso-de-solo-lectura) explica cómo aplicarla.

Si un permiso falta, el script lo dice con su nombre exacto, por ejemplo: `Falta el permiso IAM 'ec2:DescribeVolumes'.`

## Códigos de salida

| Código | Significado |
|---|---|
| `0` | Se revisaron todas las regiones sin errores (haya o no hallazgos). |
| `1` | Alguna región falló, normalmente por un permiso faltante. El resultado de las demás regiones sí se muestra. |
| `2` | No se pudo revisar nada: perfil inexistente, sin credenciales, tabla de precios inválida o sin permiso para listar regiones. |

## Desarrollo y pruebas

```bash
pip install -r requirements-dev.txt
pytest
```

Las pruebas usan [moto](https://github.com/getmoto/moto) para simular AWS y nunca se conectan a una cuenta real. La Pricing API, que moto no simula, se prueba con `botocore.Stubber`. La cobertura mínima exigida es 80 %. GitHub Actions corre las pruebas en cada push con Python 3.11, 3.12 y 3.13.

## Licencia

[MIT](LICENSE). Úsalo bajo tu propio criterio: revisa cada comando sugerido antes de ejecutarlo en tu cuenta.

---

Estoy armando un kit con más desperdicios y su automatización. Si te interesa, pídelo aquí: [ENLACE_KIT]
