"""
Lógica de datos del dashboard (no depende de Streamlit, así se puede testear aparte).

CONFIDENCIALIDAD
- Solo se leen las columnas N°Mesa, Establecimiento, Circuito y DNI/Sexo.
  Domicilio y N°Insc. NO se cargan nunca.
- De "DNI/Sexo" solo se conserva el sexo; el DNI se descarta en el mismo paso de lectura.
- Todo lo que se muestra es agregado (conteos por localidad / sexo) y las localidades con
  menos de `k` electores se agrupan en una fila "Otras" (umbral de privacidad).
"""
import io

import numpy as np
import pandas as pd

COLUMNAS_USADAS = ("N°Mesa", "Establecimiento", "Circuito", "DNI/Sexo")
SEXOS = ("Femenino", "Masculino")


# --------------------------------------------------------------------------- lectura
def leer_padron(contenido: bytes) -> pd.DataFrame:
    """Lee un padrón (.xlsx) y devuelve un DataFrame anonimizado:
    mesa, establecimiento, codigo, circuito, sexo."""
    # El archivo trae un título ("Sistema Electoral") arriba: se busca la fila de encabezados.
    muestra = pd.read_excel(io.BytesIO(contenido), header=None, nrows=15)
    fila = 1
    for i, f in muestra.iterrows():
        if f.astype(str).str.strip().eq("Circuito").any():
            fila = i
            break

    crudo = pd.read_excel(
        io.BytesIO(contenido),
        header=fila,
        usecols=lambda c: str(c).strip() in COLUMNAS_USADAS,  # no se leen Domicilio ni N°Insc.
    )
    crudo.columns = [str(c).strip() for c in crudo.columns]
    faltan = set(COLUMNAS_USADAS) - set(crudo.columns)
    if faltan:
        raise ValueError(f"Faltan columnas en el Excel: {sorted(faltan)}")

    sexo = (
        crudo["DNI/Sexo"].astype(str).str.upper()
        .str.extract(r"(MASCULINO|FEMENINO)", expand=False)
        .str.capitalize()
        .fillna("Sin dato")
    )
    cir = crudo["Circuito"].astype(str).str.strip().str.extract(r"^([0-9]+[A-Za-z]?)\s*-\s*(.+)$")

    df = pd.DataFrame(
        {
            "mesa": crudo["N°Mesa"],
            "establecimiento": crudo["Establecimiento"].astype(str).str.strip(),
            "codigo": cir[0].str.upper(),
            "circuito": cir[1].str.strip(),
            "sexo": sexo,
        }
    )
    del crudo  # el DNI no sale de esta función
    return df.dropna(subset=["codigo"]).reset_index(drop=True)


def unir_coordenadas(df: pd.DataFrame, coords: pd.DataFrame) -> pd.DataFrame:
    """Agrega localidad, lat, lon y precisión a cada registro (por código de circuito)."""
    c = coords.copy()
    c["codigo"] = c["codigo"].astype(str).str.strip().str.upper()
    out = df.merge(c[["codigo", "localidad", "lat", "lon", "precision"]], on="codigo", how="left")
    out["localidad"] = out["localidad"].fillna(out["circuito"])
    out["precision"] = out["precision"].fillna("sin coordenadas")
    return out


# --------------------------------------------------------------------------- agregación
def tabla_localidades(base: pd.DataFrame) -> pd.DataFrame:
    """Una fila por localidad con total, conteo por sexo, % de mujeres y % del total."""
    cols = ["localidad", "lat", "lon", "circuitos", "establecimientos", "mesas", "precision",
            "Total", "Femenino", "Masculino", "pct_mujeres", "pct_del_total", "acumulado_pct"]
    if base.empty:
        return pd.DataFrame(columns=cols)

    conteo = base.groupby(["localidad", "sexo"]).size().unstack(fill_value=0)
    for s in SEXOS:
        if s not in conteo.columns:
            conteo[s] = 0
    total = base.groupby("localidad").size().rename("Total")
    meta = base.groupby("localidad").agg(
        lat=("lat", "mean"),
        lon=("lon", "mean"),
        circuitos=("codigo", "nunique"),
        establecimientos=("establecimiento", "nunique"),
        mesas=("mesa", "nunique"),
        precision=("precision", lambda s: "aprox" if s.isin(["aprox", "sin coordenadas"]).any() else "alta"),
    )
    t = meta.join(total).join(conteo[list(SEXOS)]).reset_index()
    t["pct_mujeres"] = (t["Femenino"] / t["Total"] * 100).round(1)
    t["pct_del_total"] = (t["Total"] / t["Total"].sum() * 100).round(2)
    t = t.sort_values("Total", ascending=False).reset_index(drop=True)
    t["acumulado_pct"] = t["pct_del_total"].cumsum().round(1)
    return t[cols]


def agrupar_menores(t: pd.DataFrame, k: int) -> pd.DataFrame:
    """Umbral de privacidad: las localidades con menos de k electores se funden en una fila 'Otras'."""
    if k <= 1 or t.empty:
        return t.copy()
    mayores = t[t["Total"] >= k]
    menores = t[t["Total"] < k]
    if menores.empty:
        return mayores.copy()

    total_general = t["Total"].sum()
    fila = {
        "localidad": f"Otras ({len(menores)} localidades con menos de {k} electores)",
        "lat": np.nan,
        "lon": np.nan,
        "circuitos": menores["circuitos"].sum(),
        "establecimientos": menores["establecimientos"].sum(),
        "mesas": menores["mesas"].sum(),
        "precision": "-",
        "Total": menores["Total"].sum(),
        "Femenino": menores["Femenino"].sum(),
        "Masculino": menores["Masculino"].sum(),
    }
    fila["pct_mujeres"] = round(fila["Femenino"] / fila["Total"] * 100, 1)
    fila["pct_del_total"] = round(fila["Total"] / total_general * 100, 2)
    out = pd.concat([mayores, pd.DataFrame([fila])], ignore_index=True)
    out["acumulado_pct"] = out["pct_del_total"].cumsum().round(1)
    return out


def comparar_anios(t_a: pd.DataFrame, t_b: pd.DataFrame, k: int) -> pd.DataFrame:
    """Compara dos años solo en las localidades presentes en ambos (y con >= k electores en ambos)."""
    m = t_a[["localidad", "Total", "Femenino", "Masculino"]].merge(
        t_b[["localidad", "Total", "Femenino", "Masculino"]],
        on="localidad", suffixes=("_a", "_b"),
    )
    m = m[(m["Total_a"] >= k) & (m["Total_b"] >= k)].copy()
    m["variacion"] = m["Total_b"] - m["Total_a"]
    m["variacion_pct"] = (m["variacion"] / m["Total_a"] * 100).round(1)
    return m.sort_values("Total_b", ascending=False).reset_index(drop=True)
