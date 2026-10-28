"""
Dashboard: distribución territorial de electores extranjeros – Provincia de Misiones.

Ejecutar:   streamlit run app.py
Datos:      colocar los padrones .xlsx (2023 y 2025) junto a este archivo (o en ./data),
            o subirlos desde la barra lateral.
"""
from pathlib import Path
from typing import Optional
import io

import folium
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from folium.plugins import HeatMap
from plotly.subplots import make_subplots
from streamlit_folium import st_folium

import procesamiento as proc

# --------------------------------------------------------------------------- configuración
st.set_page_config(
    page_title="Electores extranjeros – Misiones",
    page_icon="🗺️",
    layout="wide",
)

BASE_DIR = Path(__file__).resolve().parent
COORD_CSV = BASE_DIR / "coordenadas_circuitos.csv"
ANIOS = (2023, 2025)
COLOR_F, COLOR_M = "#d6336c", "#1c7ed6"
COLORES_SEXO = {"Femenino": COLOR_F, "Masculino": COLOR_M, "Sin dato": "#adb5bd"}
LIMITES_MISIONES = [[-28.25, -56.15], [-25.45, -53.55]]  # [[sur, oeste], [norte, este]]
CENTRO_MISIONES = (-27.0, -54.75)


# --------------------------------------------------------------------------- utilidades
def fmt(n) -> str:
    """Número con separador de miles estilo es-AR (1.234)."""
    return f"{int(n):,}".replace(",", ".")


def mostrar_plotly(fig):
    try:
        st.plotly_chart(fig, width="stretch")
    except Exception:  # versiones anteriores de Streamlit
        st.plotly_chart(fig, use_container_width=True)


def mostrar_tabla(df, **kwargs):
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)


def buscar_archivo(anio: int) -> Optional[Path]:
    for carpeta in (BASE_DIR, BASE_DIR / "data", Path.cwd()):
        for ruta in sorted(carpeta.glob(f"*xtranjeros*{anio}*.xlsx")):
            return ruta
    return None


@st.cache_data(show_spinner="Leyendo padrón…")
def cargar_padron(contenido: bytes) -> pd.DataFrame:
    return proc.leer_padron(contenido)


@st.cache_data
def cargar_coordenadas(contenido: Optional[bytes]) -> pd.DataFrame:
    fuente = io.BytesIO(contenido) if contenido else COORD_CSV
    df = pd.read_csv(fuente, dtype={"codigo": str})
    df["codigo"] = df["codigo"].str.strip().str.upper()
    return df


# --------------------------------------------------------------------------- mapa
def pesos(serie: pd.Series, escala: str) -> pd.Series:
    if escala == "Raíz cuadrada":
        v = np.sqrt(serie.astype(float))
    elif escala == "Logarítmica":
        v = np.log1p(serie.astype(float))
    else:
        v = serie.astype(float)
    return (v / v.max()).clip(0, 1)


def color_por_pct_mujeres(p: float) -> str:
    """Interpola de azul (0 % mujeres) a rosa (100 % mujeres)."""
    p = min(max(p, 0), 100) / 100
    a = np.array([int(COLOR_M[i:i + 2], 16) for i in (1, 3, 5)])
    b = np.array([int(COLOR_F[i:i + 2], 16) for i in (1, 3, 5)])
    r, g, bl = (a + (b - a) * p).astype(int)
    return f"#{r:02x}{g:02x}{bl:02x}"


def tooltip_html(r, k: int) -> str:
    if r.Total < k:
        return f"<b>{r.localidad}</b><br>Menos de {k} electores"
    aprox = " <i>(ubicación aproximada)</i>" if r.precision != "alta" else ""
    return (
        f"<b>{r.localidad}</b>{aprox}<br>"
        f"Total: {fmt(r.Total)} ({r.pct_del_total:.1f}% de la provincia)<br>"
        f"♀ {fmt(r.Femenino)} · ♂ {fmt(r.Masculino)} ({r.pct_mujeres:.0f}% mujeres)"
    )


def construir_mapa(t, k, modo, escala, radio, blur, color_puntos, tiles):
    m = folium.Map(location=CENTRO_MISIONES, zoom_start=8, tiles=tiles, control_scale=True)
    datos = t.dropna(subset=["lat", "lon"]).copy()
    if datos.empty:
        return m
    datos["peso"] = pesos(datos["Total"], escala)

    if modo in ("Mapa de calor", "Calor + puntos"):
        HeatMap(
            datos[["lat", "lon", "peso"]].values.tolist(),
            name="Mapa de calor",
            radius=radio,
            blur=blur,
            min_opacity=0.3,
            gradient={0.2: "#2c7bb6", 0.4: "#abd9e9", 0.6: "#ffffbf", 0.8: "#fdae61", 1.0: "#d7191c"},
        ).add_to(m)

    if modo in ("Puntos proporcionales", "Calor + puntos"):
        capa = folium.FeatureGroup(name="Localidades").add_to(m)
        maximo = datos["Total"].max()
        for r in datos.itertuples():
            radio_px = 4 + 28 * np.sqrt(r.Total / maximo)
            if color_puntos == "% de mujeres" and r.Total >= k:
                color = color_por_pct_mujeres(r.pct_mujeres)
            else:
                color = "#495057" if color_puntos == "% de mujeres" else "#c92a2a"
            folium.CircleMarker(
                location=[r.lat, r.lon],
                radius=float(radio_px),
                color=color,
                weight=1,
                fill=True,
                fill_color=color,
                fill_opacity=0.6,
                tooltip=folium.Tooltip(tooltip_html(r, k)),
            ).add_to(capa)

    m.fit_bounds(LIMITES_MISIONES)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def mostrar_mapa(m):
    try:
        st_folium(m, height=650, use_container_width=True, returned_objects=[])
    except TypeError:
        st_folium(m, height=650, width=1200, returned_objects=[])


# --------------------------------------------------------------------------- barra lateral
st.sidebar.title("⚙️ Filtros")

with st.sidebar.expander("📂 Fuentes de datos (opcional)"):
    st.caption("Si los archivos están junto a app.py se detectan solos.")
    subidos = {a: st.file_uploader(f"Padrón {a} (.xlsx)", type="xlsx", key=f"up_{a}") for a in ANIOS}
    up_coords = st.file_uploader("Coordenadas por circuito (.csv)", type="csv", key="up_coords")

coords = cargar_coordenadas(up_coords.getvalue() if up_coords else None)

padrones = {}
for a in ANIOS:
    if subidos[a] is not None:
        contenido = subidos[a].getvalue()
    else:
        ruta = buscar_archivo(a)
        contenido = ruta.read_bytes() if ruta else None
    if contenido:
        try:
            padrones[a] = proc.unir_coordenadas(cargar_padron(contenido), coords)
        except Exception as e:  # archivo con formato inesperado
            st.sidebar.error(f"No se pudo leer el padrón {a}: {e}")

if not padrones:
    st.title("🗺️ Electores extranjeros – Misiones")
    st.error(
        "No encontré los padrones. Copiá los .xlsx (con '2023' y '2025' en el nombre) junto a "
        "`app.py` o subilos desde la barra lateral → *Fuentes de datos*."
    )
    st.stop()

anios_disp = sorted(padrones)
anio = st.sidebar.radio("Año del padrón", anios_disp, horizontal=True, index=len(anios_disp) - 1)
sexos_sel = st.sidebar.multiselect("Sexo", list(proc.SEXOS), default=list(proc.SEXOS))
k = st.sidebar.slider(
    "🔒 Umbral de privacidad (mín. electores)", 1, 20, 5,
    help="Las localidades con menos electores que este valor se agrupan en 'Otras' y no se "
         "muestra su desglose por sexo.",
)
top_n = st.sidebar.slider("Localidades en rankings", 5, 30, 15)

if not sexos_sel:
    st.warning("Elegí al menos un sexo en la barra lateral.")
    st.stop()

# --------------------------------------------------------------------------- datos del año elegido
base_total = padrones[anio]                                   # ambos sexos
base = base_total[base_total["sexo"].isin(sexos_sel)]         # filtrado
t = proc.tabla_localidades(base)
t_priv = proc.agrupar_menores(t, k)
t_sexo = proc.tabla_localidades(base_total)                   # para la pestaña de sexo
t_sexo_priv = proc.agrupar_menores(t_sexo, k)
solo_localidades = t_priv[~t_priv["localidad"].str.startswith("Otras")]

# --------------------------------------------------------------------------- encabezado y KPIs
st.title("🗺️ Electores extranjeros – Provincia de Misiones")
st.caption(
    f"Padrón {anio} · datos agregados por localidad (sin DNI, domicilio ni datos personales) · "
    f"umbral de privacidad: {k}"
)

total = len(base)
top1 = t.iloc[0]
top5 = t["pct_del_total"].head(5).sum()
mujeres = int((base_total["sexo"] == "Femenino").sum())
hombres = int((base_total["sexo"] == "Masculino").sum())

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Electores (filtro actual)", fmt(total))
c2.metric("Mujeres / Hombres", f"{fmt(mujeres)} / {fmt(hombres)}",
          f"{mujeres / max(mujeres + hombres, 1) * 100:.1f}% mujeres", delta_color="off")
c3.metric("Localidades", fmt(len(t)))
c4.metric("Mayor concentración", top1["localidad"], f"{top1['pct_del_total']:.1f}% del total", delta_color="off")
c5.metric("Top 5 localidades", f"{top5:.1f}%", "del total", delta_color="off")

tab_res, tab_mapa, tab_sexo, tab_evol, tab_datos, tab_priv = st.tabs(
    ["📊 Resumen", "🔥 Mapa de calor", "⚧ Comparación por sexo",
     "📅 2023 vs 2025", "📋 Datos agregados", "🔒 Privacidad"]
)

# --------------------------------------------------------------------------- Resumen
with tab_res:
    izq, der = st.columns([3, 2])

    with izq:
        st.subheader(f"Top {top_n} localidades con más electores")
        top = solo_localidades.head(top_n)
        largo = top.melt(id_vars="localidad", value_vars=sexos_sel, var_name="sexo", value_name="electores")
        fig = px.bar(
            largo, x="electores", y="localidad", color="sexo", orientation="h",
            color_discrete_map=COLORES_SEXO,
            category_orders={"localidad": top["localidad"].tolist()[::-1]},
            labels={"electores": "Electores", "localidad": "", "sexo": "Sexo"},
        )
        fig.update_layout(height=max(380, 26 * len(top) + 120), legend_title_text="",
                          margin=dict(l=0, r=0, t=10, b=0))
        mostrar_plotly(fig)

    with der:
        st.subheader("Peso relativo de cada localidad")
        kw = {}
        if len(sexos_sel) == 2:
            kw = dict(color="pct_mujeres", range_color=(20, 80),
                      color_continuous_scale=[COLOR_M, "#f1f3f5", COLOR_F],
                      labels={"pct_mujeres": "% mujeres"})
        fig = px.treemap(solo_localidades, path=["localidad"], values="Total", **kw)
        fig.update_layout(height=max(380, 26 * min(len(top), top_n) + 120), margin=dict(l=0, r=0, t=10, b=0))
        mostrar_plotly(fig)
        if kw:
            st.caption("Tamaño = cantidad de electores · color = % de mujeres (azul: más hombres, rosa: más mujeres).")

    st.subheader("Concentración acumulada (Pareto)")
    st.caption("¿Cuántas localidades concentran la mayor parte de los electores?")
    pareto = solo_localidades.head(top_n)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=pareto["localidad"], y=pareto["Total"], name="Electores", marker_color="#868e96")
    fig.add_scatter(x=pareto["localidad"], y=pareto["acumulado_pct"], name="% acumulado",
                    mode="lines+markers", line=dict(color="#d7191c"), secondary_y=True)
    fig.update_yaxes(title_text="Electores", secondary_y=False)
    fig.update_yaxes(title_text="% acumulado", range=[0, 100], secondary_y=True)
    fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1))
    mostrar_plotly(fig)

# --------------------------------------------------------------------------- Mapa de calor
with tab_mapa:
    st.subheader(f"Distribución territorial – padrón {anio}")
    a1, a2, a3, a4, a5 = st.columns([1.3, 1.1, 1, 1, 1.1])
    modo = a1.radio("Visualización", ["Mapa de calor", "Puntos proporcionales", "Calor + puntos"], index=2)
    escala = a2.selectbox("Escala de intensidad", ["Raíz cuadrada", "Lineal", "Logarítmica"],
                          help="Raíz/log evitan que Posadas 'tape' al resto de las localidades.")
    radio = a3.slider("Radio del calor", 10, 80, 35)
    blur = a4.slider("Difuminado", 5, 60, 25)
    color_puntos = a5.selectbox("Color de los puntos", ["Cantidad", "% de mujeres"])
    estilo = st.radio("Mapa base", ["Claro", "Calles (OpenStreetMap)"], horizontal=True)
    tiles = "CartoDB positron" if estilo == "Claro" else "OpenStreetMap"

    mapa = construir_mapa(t, k, modo, escala, radio, blur, color_puntos, tiles)
    mostrar_mapa(mapa)

    st.caption(
        "Cada punto representa el **centro de una localidad/circuito**, no un domicilio: "
        "el mapa muestra concentración territorial, nunca ubicaciones individuales."
    )
    if color_puntos == "% de mujeres":
        st.caption("🔵 predominan hombres · 🟣 equilibrado · 🌸 predominan mujeres (gris: menos de "
                   f"{k} electores).")
    aprox = t[t["precision"] != "alta"]["localidad"].tolist()
    if aprox:
        with st.expander(f"ℹ️ {len(aprox)} localidades con coordenadas aproximadas"):
            st.write(", ".join(sorted(aprox)))
            st.caption("Podés corregirlas editando `coordenadas_circuitos.csv` (columnas lat/lon).")

# --------------------------------------------------------------------------- Sexo
with tab_sexo:
    st.subheader(f"Comparación por sexo – padrón {anio}")
    st.caption("Esta pestaña usa a todos los electores del año, sin el filtro de sexo de la barra lateral.")
    s1, s2 = st.columns([1, 2])

    with s1:
        dona = base_total["sexo"].value_counts().reindex(list(proc.SEXOS)).dropna().reset_index()
        dona.columns = ["sexo", "electores"]
        fig = px.pie(dona, names="sexo", values="electores", hole=0.5,
                     color="sexo", color_discrete_map=COLORES_SEXO)
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), legend_title_text="")
        mostrar_plotly(fig)

    with s2:
        topS = t_sexo_priv[~t_sexo_priv["localidad"].str.startswith("Otras")].head(top_n)
        largo = topS.melt(id_vars="localidad", value_vars=list(proc.SEXOS), var_name="sexo", value_name="electores")
        fig = px.bar(largo, x="localidad", y="electores", color="sexo", barmode="group",
                     color_discrete_map=COLORES_SEXO, labels={"electores": "Electores", "localidad": ""})
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), legend_title_text="")
        mostrar_plotly(fig)

    st.subheader("¿Dónde predominan mujeres u hombres?")
    minimo = st.slider("Mínimo de electores para calcular el porcentaje", max(k, 10), 200, 50, step=10,
                       help="Con pocos electores el porcentaje es inestable y puede identificar personas.")
    pct = t_sexo[t_sexo["Total"] >= minimo].sort_values("pct_mujeres")
    if pct.empty:
        st.info("Ninguna localidad alcanza ese mínimo.")
    else:
        global_f = (base_total["sexo"] == "Femenino").mean() * 100
        fig = px.bar(pct, x="pct_mujeres", y="localidad", orientation="h",
                     color="pct_mujeres", range_color=(20, 80),
                     color_continuous_scale=[COLOR_M, "#f1f3f5", COLOR_F],
                     labels={"pct_mujeres": "% de mujeres", "localidad": ""},
                     hover_data={"Total": True})
        fig.add_vline(x=50, line_dash="dot", line_color="#868e96")
        fig.add_vline(x=global_f, line_dash="dash", line_color="#212529",
                      annotation_text=f"Provincia: {global_f:.1f}%", annotation_position="top")
        fig.update_xaxes(range=[0, 100])
        fig.update_layout(height=max(320, 24 * len(pct) + 120), margin=dict(l=0, r=0, t=30, b=0),
                          coloraxis_showscale=False)
        mostrar_plotly(fig)

# --------------------------------------------------------------------------- Comparación entre años
with tab_evol:
    if len(anios_disp) < 2:
        st.info("Se necesitan los padrones de dos años para comparar.")
    else:
        A, B = anios_disp[0], anios_disp[-1]
        bA = padrones[A][padrones[A]["sexo"].isin(sexos_sel)]
        bB = padrones[B][padrones[B]["sexo"].isin(sexos_sel)]
        tA, tB = proc.tabla_localidades(bA), proc.tabla_localidades(bB)
        comp = proc.comparar_anios(tA, tB, k)

        st.subheader(f"Comparación {A} vs {B}")
        st.warning(
            f"**Ojo con la cobertura:** el padrón {B} tiene {fmt(len(bB))} electores en {len(tB)} localidades, "
            f"y el {A} tiene {fmt(len(bA))} en {len(tA)}. Los totales **no son comparables** (el archivo {B} "
            f"podría ser parcial), por eso se comparan solo las {len(comp)} localidades presentes en ambos años "
            f"(con al menos {k} electores en cada uno)."
        )
        if comp.empty:
            st.info("No hay localidades en común que superen el umbral de privacidad.")
        else:
            topC = comp.head(top_n)
            largo = topC.melt(id_vars="localidad", value_vars=["Total_a", "Total_b"],
                              var_name="anio", value_name="electores")
            largo["anio"] = largo["anio"].map({"Total_a": str(A), "Total_b": str(B)})
            fig = px.bar(largo, x="localidad", y="electores", color="anio", barmode="group",
                         labels={"electores": "Electores", "localidad": "", "anio": "Año"},
                         color_discrete_sequence=["#adb5bd", "#e8590c"])
            fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0))
            mostrar_plotly(fig)

            vis = comp.rename(columns={
                "Total_a": f"Total {A}", "Total_b": f"Total {B}",
                "Femenino_a": f"Mujeres {A}", "Femenino_b": f"Mujeres {B}",
                "Masculino_a": f"Hombres {A}", "Masculino_b": f"Hombres {B}",
                "variacion": "Variación", "variacion_pct": "Variación %", "localidad": "Localidad",
            })
            mostrar_tabla(vis)

# --------------------------------------------------------------------------- Datos agregados
with tab_datos:
    st.subheader(f"Tabla por localidad – padrón {anio}")
    vista = t_priv.rename(columns={
        "localidad": "Localidad", "Total": "Electores", "Femenino": "Mujeres", "Masculino": "Hombres",
        "pct_mujeres": "% mujeres", "pct_del_total": "% del total", "acumulado_pct": "% acumulado",
        "circuitos": "Circuitos", "establecimientos": "Establecimientos", "precision": "Ubicación en mapa",
    })[["Localidad", "Electores", "Mujeres", "Hombres", "% mujeres", "% del total", "% acumulado",
        "Circuitos", "Establecimientos", "Ubicación en mapa"]]
    mostrar_tabla(vista)
    st.download_button(
        "⬇️ Descargar tabla agregada (CSV)",
        vista.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"electores_extranjeros_misiones_{anio}_agregado.csv",
        mime="text/csv",
    )

# --------------------------------------------------------------------------- Privacidad
with tab_priv:
    st.subheader("Cómo se protege la confidencialidad")
    st.markdown(
        f"""
- **Columnas que nunca se cargan:** *Domicilio* y *N°Insc.* (la lectura del Excel las excluye).
- **DNI descartado:** de la columna *DNI/Sexo* se conserva únicamente el sexo; el DNI no se guarda ni se muestra.
- **Solo datos agregados:** todos los gráficos, mapas y tablas son conteos por localidad y sexo; no hay
  vistas de registros individuales.
- **Umbral de privacidad (actual: {k}):** las localidades con menos de {k} electores se agrupan en una
  fila *Otras* y en el mapa solo se informa «menos de {k} electores», sin desglose por sexo.
- **Porcentajes estables:** en la pestaña de sexo solo se calculan porcentajes para localidades con un
  mínimo de electores.
- **Ubicación:** los puntos del mapa son el centro de cada localidad, no domicilios.
"""
    )
