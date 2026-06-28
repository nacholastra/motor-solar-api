"""
Motor de simulación solar — única fuente de verdad del SaaS.

Dimensionamiento:
    kWp = (Consumo_Anual_kWh × %_Ahorro) / (HPS_anual × PR)
    HPS_anual = HPS_diaria_regional × 365
"""

from typing import Optional

PR = 0.80
INFLACION_ENERGETICA = 0.03
GASTO_MENSUAL_MINIMO = 20.0
ANOS_PROYECCION_DEFAULT = 20

HPS_DIARIA_POR_REGION = {
    "andalucia": 5.2365,
    "madrid": 4.8365,
    "cataluna": 4.6000,
    "valencia": 5.0000,
    "galicia": 3.8000,
    "castilla_leon": 4.5000,
    "pais_vasco": 3.6000,
    "canarias": 5.4000,
}

COSTO_KWH_POR_REGION = {
    "andalucia": 0.14,
    "madrid": 0.15,
    "cataluna": 0.16,
    "valencia": 0.15,
    "galicia": 0.16,
    "castilla_leon": 0.15,
    "pais_vasco": 0.16,
    "canarias": 0.13,
}

CONFIG_MERCADO = {
    "residencial": {
        "costo_instalacion_kw": 1400.0,
        "porcentaje_ahorro": 0.70,
        "ratio_fijo": 0.35,
    },
    "industrial": {
        "costo_instalacion_kw": 900.0,
        "porcentaje_ahorro": 0.80,
        "ratio_fijo": 0.20,
    },
}


class SimulacionError(Exception):
    pass


def _normalizar_region(region: str) -> str:
    region = region.lower().strip()
    if region not in HPS_DIARIA_POR_REGION:
        raise SimulacionError(
            f"Región no válida: '{region}'. "
            f"Use una de: {', '.join(sorted(HPS_DIARIA_POR_REGION))}"
        )
    return region


def calcular_simulacion(
    gasto_mensual: float,
    tipo_cliente: str,
    region: str = "madrid",
    anos_proyeccion: int = ANOS_PROYECCION_DEFAULT,
    consumo_mensual_kwh: Optional[float] = None,
) -> dict:
    if gasto_mensual < GASTO_MENSUAL_MINIMO:
        raise SimulacionError(
            f"El gasto mensual debe ser al menos {GASTO_MENSUAL_MINIMO:.0f} €/mes."
        )

    tipo_cliente = tipo_cliente.lower().strip()
    if tipo_cliente not in CONFIG_MERCADO:
        raise SimulacionError(
            "Tipo de cliente no válido. Use 'residencial' o 'industrial'."
        )

    region = _normalizar_region(region)

    if anos_proyeccion < 1 or anos_proyeccion > 30:
        raise SimulacionError("Los años de proyección deben estar entre 1 y 30.")

    conf = CONFIG_MERCADO[tipo_cliente]
    hps_diaria = HPS_DIARIA_POR_REGION[region]
    hps_anual = hps_diaria * 365
    costo_kwh = COSTO_KWH_POR_REGION[region]

    porcentaje_ahorro = conf["porcentaje_ahorro"]
    ratio_fijo = conf["ratio_fijo"]
    costo_instalacion_kw = conf["costo_instalacion_kw"]

    gasto_anual_inicial = gasto_mensual * 12

    if consumo_mensual_kwh is not None and consumo_mensual_kwh > 0:
        consumo_anual_kwh = consumo_mensual_kwh * 12
    else:
        consumo_anual_kwh = gasto_anual_inicial / costo_kwh

    produccion_esperada_por_kwp = hps_anual * PR
    tamano_sistema_kw = (consumo_anual_kwh * porcentaje_ahorro) / produccion_esperada_por_kwp
    inversion_inicial = tamano_sistema_kw * costo_instalacion_kw

    coste_fijo_anual = gasto_anual_inicial * ratio_fijo
    coste_variable_anual = gasto_anual_inicial * (1 - ratio_fijo)

    gasto_acumulado_sin_solar = 0.0
    gasto_acumulado_con_solar = inversion_inicial
    ahorro_acumulado = 0.0

    coste_variable_corriente = coste_variable_anual
    payback_anos: Optional[float] = None

    detalle_anual = []

    for ano in range(1, anos_proyeccion + 1):
        if ano > 1:
            coste_variable_corriente *= (1 + INFLACION_ENERGETICA)

        ahorro_anual = coste_variable_corriente * porcentaje_ahorro
        gasto_anual_sin_solar = coste_fijo_anual + coste_variable_corriente
        gasto_anual_con_solar = coste_fijo_anual + coste_variable_corriente * (1 - porcentaje_ahorro)

        gasto_acumulado_sin_solar += gasto_anual_sin_solar
        gasto_acumulado_con_solar += gasto_anual_con_solar

        ahorro_previo = ahorro_acumulado
        ahorro_acumulado += ahorro_anual

        if payback_anos is None and ahorro_acumulado >= inversion_inicial:
            if ahorro_anual > 0:
                fraccion = (inversion_inicial - ahorro_previo) / ahorro_anual
                payback_anos = round((ano - 1) + fraccion, 1)
            else:
                payback_anos = float(ano)

        detalle_anual.append({
            "ano": ano,
            "coste_variable": round(coste_variable_corriente, 2),
            "ahorro_anual": round(ahorro_anual, 2),
            "gasto_sin_solar": round(gasto_anual_sin_solar, 2),
            "gasto_con_solar": round(gasto_anual_con_solar, 2),
        })

    ahorro_neto_total = gasto_acumulado_sin_solar - gasto_acumulado_con_solar

    return {
        "tipo_cliente": tipo_cliente,
        "region": region,
        "gasto_mensual_eur": round(gasto_mensual, 2),
        "consumo_anual_kwh": round(consumo_anual_kwh, 0),
        "tamano_sistema_kw": round(tamano_sistema_kw, 2),
        "inversion_estimada_eur": round(inversion_inicial, 2),
        "ahorro_neto_total_eur": round(ahorro_neto_total, 2),
        "tiempo_retorno_anos": payback_anos if payback_anos is not None else f"Más de {anos_proyeccion} años",
        "anos_proyeccion": anos_proyeccion,
        "parametros": {
            "pr": PR,
            "hps_diaria": hps_diaria,
            "hps_anual": round(hps_anual, 2),
            "ratio_fijo": ratio_fijo,
            "porcentaje_ahorro": porcentaje_ahorro,
            "inflacion_energetica": INFLACION_ENERGETICA,
            "costo_instalacion_kw": costo_instalacion_kw,
        },
        "gasto_total_sin_solar_eur": round(gasto_acumulado_sin_solar, 2),
        "gasto_total_con_solar_eur": round(gasto_acumulado_con_solar, 2),
        "detalle_anual": detalle_anual,
    }


if __name__ == "__main__":
    for perfil in [
        {"gasto_mensual": 120, "tipo_cliente": "residencial", "region": "madrid"},
        {"gasto_mensual": 1500, "tipo_cliente": "industrial", "region": "andalucia"},
        {"gasto_mensual": 15, "tipo_cliente": "residencial", "region": "madrid"},
    ]:
        print(f"\n--- {perfil} ---")
        try:
            r = calcular_simulacion(**perfil)
            print(f"  kWp: {r['tamano_sistema_kw']} | Inversión: {r['inversion_estimada_eur']} €")
            print(f"  Payback: {r['tiempo_retorno_anos']} | Ahorro neto 20a: {r['ahorro_neto_total_eur']} €")
        except SimulacionError as e:
            print(f"  ERROR: {e}")
