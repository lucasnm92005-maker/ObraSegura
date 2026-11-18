"""ZONA LIBRE: la interfaz de ObraSegura para Cimiento Seguros.
Usa solo las funciones de la zona fija (core/). El pie de página (config["pie"]) debe quedar al final.

Para verla en su computador:   streamlit run app.py"""
import re

import altair as alt
import pandas as pd
import streamlit as st

from core import (cargar_config, cargar_metadata, cargar_modelo, cargar_resultados, etiqueta, evaluar,
                  hay_modelo, texto_razon, validar)

config = cargar_config()
st.set_page_config(page_title=config["titulo"], page_icon="🛡️", layout="wide")

# ---------------------------------------------------------------------------------------------
# Colores y textos de Cimiento (funcionan en tema claro y oscuro)
# ---------------------------------------------------------------------------------------------
VERDE, NARANJA, ROJO, AZUL, GRIS = "#2E9E4F", "#F08C00", "#D93A3A", "#2F80ED", "#9AA0A6"
COLOR = {"Tarifa estándar": VERDE, "Recargo": NARANJA, "Recargo + garantías": ROJO}
ICONO = {"Tarifa estándar": "✅", "Recargo": "⚠️", "Recargo + garantías": "🛑"}
QUE_HACER = {
    "Tarifa estándar": "Expedir la póliza con la tarifa estándar.",
    "Recargo": "Expedir la póliza con recargo.",
    "Recargo + garantías": "Expedir con recargo y exigir garantías adicionales (contragarantía o codeudor). "
                           "Está entre el 10 % de mayor riesgo.",
}
AVISO = ("La probabilidad es una **estimación de riesgo** basada en contratos anteriores, no una prueba de que la "
         "entidad o el contratista hayan hecho algo mal.")
TASA_PROMEDIO = 0.195          # tasa de atraso de los contratos con desenlace conocido (2020–2025)
SI_NO = ["cierre_vigencia", "ent_sin_historia", "prov_sin_historia", "puede_prorrogarse", "es_consorcio_ut", "en_rues"]
PRINCIPALES = ["tipo_de_contrato", "modalidad", "valor_del_contrato", "duracion_pactada_dias", "departamento", "sector",
               "orden", "tipo_obra", "mes_firma", "cierre_vigencia", "ent_tasa_suav", "ent_contratos_previos",
               "es_consorcio_ut", "perfil_contratista"]
AYUDA = {
    "ent_tasa_suav": "Proporción de contratos anteriores de la entidad que se atrasaron, ajustada por cuántos tiene "
                     "(0 = nunca se atrasa; 0,35 = muy alta). Si la entidad no tiene historia, deje el valor típico.",
    "prov_tasa_suav": "Igual que la de la entidad, pero para el contratista.",
    "plazo_relativo": "Plazo pactado frente a contratos del mismo tipo y valor parecido: 0 = normal; "
                      "−0,5 = bastante más corto; +0,5 = bastante más largo.",
    "valor_del_contrato": "En pesos colombianos.",
    "pct_anticipo": "Proporción del valor que se paga por anticipado (0 a 0,5).",
}
# Importancia por permutación del modelo en la prueba 2024–2025 (cuaderno, sección 14)
IMPORTANCIA = [("Historia de atrasos de la entidad", 0.046), ("Valor del contrato", 0.033), ("Plazo pactado", 0.033),
               ("Tipo de obra", 0.013), ("Contratos previos de la entidad", 0.009), ("Mes de firma", 0.009),
               ("Plazo frente a contratos parecidos", 0.008), ("Departamento", 0.003),
               ("Historia del contratista", 0.002)]

st.markdown("""
<style>
.tarjeta {border-radius: 14px; padding: 18px 22px; color: white; margin: 4px 0 10px 0;}
.tarjeta .titulo {font-size: 0.85rem; opacity: 0.9; text-transform: uppercase; letter-spacing: .05em;}
.tarjeta .valor {font-size: 2.0rem; font-weight: 800; line-height: 1.15;}
.tarjeta .detalle {font-size: 0.95rem; opacity: 0.95; margin-top: 4px;}
.chip {display:inline-block; padding: 2px 10px; border-radius: 999px; color: white; font-size: .85rem; font-weight: 600;}
</style>""", unsafe_allow_html=True)


def coma(texto):
    """Decimales con coma: '41.6 puntos' → '41,6 puntos'."""
    return re.sub(r"(\d)\.(\d+) (pts|puntos)", r"\1,\2 \3", str(texto))


def pct(p):
    return f"{p:.0%}".replace("%", " %")


def miles(x):
    return f"{x:,.0f}".replace(",", ".")


def tarjeta_html(titulo, valor, detalle, color):
    st.markdown(f'<div class="tarjeta" style="background:{color}"><div class="titulo">{titulo}</div>'
                f'<div class="valor">{valor}</div><div class="detalle">{detalle}</div></div>', unsafe_allow_html=True)


def chip(decision):
    return f'<span class="chip" style="background:{COLOR.get(decision, GRIS)}">{ICONO.get(decision, "")} {decision}</span>'


# ---------------------------------------------------------------------------------------------
# Encabezado
# ---------------------------------------------------------------------------------------------
col_logo, col_titulo = st.columns([1, 9])
with col_logo:
    try:
        st.image(config["logo"], width=90)
    except Exception:
        st.markdown("<div style='font-size:64px'>🛡️</div>", unsafe_allow_html=True)
with col_titulo:
    st.title(config["titulo"])
    st.caption(f"{config['cliente']} · {config['descripcion']}")

if not hay_modelo():
    st.info("Todavía no hay modelo en la carpeta model/. Sigan la guía del README.")
    st.divider()
    st.caption(config["pie"])
    st.stop()


@st.cache_resource
def recursos():
    return cargar_metadata(), cargar_modelo()


@st.cache_data
def tabla():
    r = cargar_resultados()
    if r is None:
        return None
    r = r.copy()
    r["id_contrato"] = r["id_contrato"].astype(str)
    radar = r["conjunto"].str.contains("radar", case=False, na=False)
    r["prioridad"] = pd.NA
    r.loc[radar, "prioridad"] = r.loc[radar, "probabilidad"].rank(ascending=False, method="first").astype(int)
    return r


meta, modelo = recursos()
res = tabla()
m = meta["metricas"]
U1, U2 = meta["umbrales"]
DECISIONES = meta["decisiones"]
ESCALA = alt.Scale(domain=DECISIONES, range=[COLOR.get(d, GRIS) for d in DECISIONES])


# ---------------------------------------------------------------------------------------------
# Gráficos reutilizables
# ---------------------------------------------------------------------------------------------
def barra_riesgo(p=None, alto=95):
    """Escala de riesgo con sus tres zonas y, si hay un contrato, dónde cae."""
    zonas = pd.DataFrame({"desde": [0, U1, U2], "hasta": [U1, U2, 1.0], "Recomendación": DECISIONES})
    zonas["inicio"] = zonas["desde"] + 0.008
    base = alt.Chart(zonas)
    capas = [
        base.mark_rect(opacity=0.85, cornerRadius=3).encode(
            x=alt.X("desde:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%", title=None, tickCount=10)),
            x2="hasta:Q", color=alt.Color("Recomendación:N", scale=ESCALA, legend=None), y=alt.value(28), y2=alt.value(62)),
        base.mark_text(color="white", fontWeight="bold", fontSize=12, align="left").encode(
            x="inicio:Q", y=alt.value(45), text="Recomendación:N"),
    ]
    prom = pd.DataFrame({"x": [TASA_PROMEDIO], "t": [f"promedio {pct(TASA_PROMEDIO)}"]})
    capas += [alt.Chart(prom).mark_rule(strokeDash=[3, 2], color=GRIS, strokeWidth=2).encode(x="x:Q", y=alt.value(18), y2=alt.value(30)),
              alt.Chart(prom).mark_text(color=GRIS, fontSize=11, dy=-2).encode(x="x:Q", y=alt.value(12), text="t:N")]
    if p is not None:
        punto = pd.DataFrame({"x": [p], "t": [f"este contrato: {pct(p)}"]})
        capas += [alt.Chart(punto).mark_rule(color=AZUL, strokeWidth=4).encode(x="x:Q", y=alt.value(20), y2=alt.value(70)),
                  alt.Chart(punto).mark_point(shape="triangle-down", size=260, filled=True, color=AZUL).encode(x="x:Q", y=alt.value(16)),
                  alt.Chart(punto).mark_text(color=AZUL, fontWeight="bold", fontSize=13, dy=0).encode(x="x:Q", y=alt.value(84), text="t:N")]
    return alt.layer(*capas).properties(height=alto)


def grafico_razones(razones):
    """Barras divergentes: cuánto sube (rojo) o baja (verde) la probabilidad cada característica."""
    filas = []
    for r in razones:
        if isinstance(r, dict):
            filas.append({"Característica": coma(f"{r['etiqueta']} = {r['valor']}"), "Puntos": r["efecto"] * 100})
        else:
            mm = re.match(r"^(.*) (sube|baja)(?: la probabilidad)? ([\d.,]+) (?:pts|puntos)$", str(r))
            if mm:
                v = float(mm.group(3).replace(",", "."))
                filas.append({"Característica": mm.group(1), "Puntos": v if mm.group(2) == "sube" else -v})
    if not filas:
        return None
    d = pd.DataFrame(filas)
    d["Efecto"] = d["Puntos"].map(lambda v: "Sube el riesgo" if v > 0 else "Baja el riesgo")
    d["Texto"] = d["Puntos"].map(lambda v: (f"+{v:.1f}" if v > 0 else f"{v:.1f}").replace(".", ",") + " pts")
    base = alt.Chart(d).encode(y=alt.Y("Característica:N", sort=None, title=None, axis=alt.Axis(labelLimit=380, labelFontSize=12)))
    barras = base.mark_bar(cornerRadius=4, height=22).encode(
        x=alt.X("Puntos:Q", title="Puntos de probabilidad frente a un contrato típico"),
        color=alt.Color("Efecto:N", scale=alt.Scale(domain=["Sube el riesgo", "Baja el riesgo"], range=[ROJO, VERDE]),
                        legend=alt.Legend(orient="top", title=None)))
    textos = base.mark_text(align="left", dx=5, fontWeight="bold").encode(x="Puntos:Q", text="Texto:N")
    cero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=GRIS).encode(x="x:Q")
    return (barras + textos + cero).properties(height=40 * len(d) + 40)


def dona(conteos, alto=230):
    d = conteos.rename_axis("Recomendación").reset_index(name="Contratos")
    d["%"] = d["Contratos"] / d["Contratos"].sum()
    return alt.Chart(d).mark_arc(innerRadius=58, outerRadius=100, stroke="white", strokeWidth=2).encode(
        theta="Contratos:Q", color=alt.Color("Recomendación:N", scale=ESCALA, legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Recomendación:N", alt.Tooltip("Contratos:Q", format=","), alt.Tooltip("%:Q", format=".0%")]
    ).properties(height=alto)


def tarjeta(probabilidad, decision, razones, tipo=None):
    """Cómo se ve la evaluación de un contrato."""
    c1, c2 = st.columns([1, 1.6])
    with c1:
        tarjeta_html("Probabilidad de atraso", pct(probabilidad),
                     f"{probabilidad / TASA_PROMEDIO:.1f} veces el promedio de los contratos".replace(".", ","),
                     COLOR.get(decision, GRIS))
    with c2:
        tarjeta_html("Recomendación", f"{ICONO.get(decision, '')} {decision}", QUE_HACER.get(decision, ""),
                     COLOR.get(decision, GRIS))
    st.altair_chart(barra_riesgo(probabilidad), width="stretch")
    if tipo == "Interventoría" and decision == "Tarifa estándar":
        st.warning("**Salvaguarda de interventorías:** las interventorías se atrasan cada vez más (37 % en 2024–2025) y "
                   "ahí el modelo se queda corto. La política recomendada es cobrarles recargo a todas.")
    st.markdown("**¿Por qué? Las características que más mueven la probabilidad de este contrato**")
    g = grafico_razones(razones)
    if g is None:
        st.caption("Con estos valores ninguna característica mueve la probabilidad frente a un contrato típico.")
    else:
        st.altair_chart(g, width="stretch")
    st.caption("Las razones muestran de qué depende la predicción frente a un contrato típico; no dicen qué pasaría "
               "si la entidad o el contratista cambiaran esa característica.")
    st.info(AVISO, icon="ℹ️")


# ---------------------------------------------------------------------------------------------
# Pestaña 1: evaluar un contrato
# ---------------------------------------------------------------------------------------------
def buscar():
    if res is None:
        st.info("No hay tabla de contratos exportada.")
        return
    elegido = st.selectbox("Identificador del contrato en SECOP II", res["id_contrato"], index=None,
                           placeholder="Escriba o pegue el identificador, por ejemplo CO1.PCCNTR.8558142")
    if not elegido:
        st.caption(f"La lista tiene {miles(len(res))} contratos: {miles(res['prioridad'].notna().sum())} en ejecución "
                   f"(radar) y {miles(res['prioridad'].isna().sum())} de prueba 2024–2025 ya terminados.")
        st.altair_chart(barra_riesgo(), width="stretch")
        return
    f = res[res["id_contrato"] == elegido].iloc[0]
    st.markdown(f"**{f['nombre_entidad']}** · {f['departamento']} · {f['tipo_de_contrato']} · {f['modalidad']}  \n"
                f"*{f['conjunto']}*" + (f" · prioridad **{int(f['prioridad'])}** de {miles(res['prioridad'].notna().sum())} "
                                        "en el radar" + (" ⭐" if int(f['prioridad']) <= 1000 else "")
                                        if pd.notna(f["prioridad"]) else ""))
    razones = [x for x in str(f.get("razones", "")).split(" · ") if x and x != "nan"]
    tarjeta(float(f["probabilidad"]), f["decision"], [coma(x) for x in razones], f["tipo_de_contrato"])


def campo(col):
    nombre, texto = col["nombre"], etiqueta(meta, col["nombre"])
    texto = texto.replace(" (1 = sí)", "")
    if nombre in SI_NO:
        defecto = 1 if float(col.get("referencia", 0)) >= 0.5 else 0
        return 1 if st.selectbox(texto, ["No", "Sí"], index=defecto, key=nombre) == "Sí" else 0
    if col["tipo"] == "numérica":
        if nombre == "valor_del_contrato":
            return st.number_input(texto, value=float(round(col["referencia"], -6)), step=10_000_000.0, format="%.0f",
                                   min_value=1_000_000.0, key=nombre, help=AYUDA.get(nombre))
        if nombre in ("duracion_pactada_dias", "ent_contratos_previos", "prov_contratos_previos"):
            return st.number_input(texto, value=float(round(col["referencia"])), step=1.0, format="%.0f",
                                   min_value=0.0, key=nombre)
        return st.number_input(texto, value=float(round(col["referencia"], 3)), step=0.01, key=nombre,
                               help=AYUDA.get(nombre))
    opciones = col.get("categorias") or [""]
    ref = col.get("referencia")
    return st.selectbox(texto, opciones, index=opciones.index(ref) if ref in opciones else 0, key=nombre)


def nuevo():
    st.caption("Llene lo que sepa del contrato el día de la firma. Lo que no cambie queda con el valor más típico "
               "de los contratos de 2020–2023.")
    cols = {c["nombre"]: c for c in meta["columnas"]}
    valores = {}
    with st.form("nuevo"):
        a, b = st.columns(2)
        for i, nombre in enumerate([n for n in PRINCIPALES if n in cols]):
            with (a if i % 2 == 0 else b):
                valores[nombre] = campo(cols[nombre])
        with st.expander("Más características (opcional)"):
            a2, b2 = st.columns(2)
            resto = [n for n in cols if n not in PRINCIPALES]
            for i, nombre in enumerate(resto):
                with (a2 if i % 2 == 0 else b2):
                    valores[nombre] = campo(cols[nombre])
        enviado = st.form_submit_button("Evaluar contrato", type="primary")
    if enviado:
        datos, errores, avisos = validar(pd.DataFrame([valores]), meta)
        for e in errores:
            st.error(e)
        for x in avisos:
            st.warning(x)
        if not errores:
            r = evaluar(modelo, meta, datos)[0]
            tarjeta(r["probabilidad"], r["decision"], r["razones"], valores.get("tipo_de_contrato"))


# ---------------------------------------------------------------------------------------------
# Pestaña 2: radar de contratos en ejecución
# ---------------------------------------------------------------------------------------------
def barras_apiladas(vista, columna, titulo, n=10):
    top = vista[columna].value_counts().head(n).index
    d = vista[vista[columna].isin(top)].groupby([columna, "decision"]).size().reset_index(name="Contratos")
    d["orden"] = d["decision"].map({x: i for i, x in enumerate(DECISIONES)})
    return alt.Chart(d).mark_bar(cornerRadius=3).encode(
        y=alt.Y(f"{columna}:N", sort=list(top), title=None, axis=alt.Axis(labelLimit=300, labelFontSize=11)),
        x=alt.X("Contratos:Q", title="Contratos", axis=alt.Axis(format="d")),
        color=alt.Color("decision:N", scale=ESCALA, title=None, legend=alt.Legend(orient="top")),
        order=alt.Order("orden:Q", sort="ascending"),
        tooltip=[f"{columna}:N", "decision:N", "Contratos:Q"]).properties(title=titulo, height=28 * len(top) + 50)


def histograma(vista):
    d = vista.assign(p=vista["probabilidad"])
    barras = alt.Chart(d).mark_bar(opacity=0.9).encode(
        x=alt.X("p:Q", bin=alt.Bin(step=0.025, extent=[0, 1]), title="Probabilidad de atraso",
                axis=alt.Axis(format="%")),
        y=alt.Y("count():Q", title="Contratos", axis=alt.Axis(format="d")),
        color=alt.Color("decision:N", scale=ESCALA, legend=None))
    lineas = alt.Chart(pd.DataFrame({"x": [U1, U2], "t": [f"recargo desde {pct(U1)}", f"garantías desde {pct(U2)}"]}))
    reglas = lineas.mark_rule(strokeDash=[5, 3], color=GRIS).encode(x="x:Q")
    textos = lineas.mark_text(align="left", dx=4, dy=-6, color=GRIS, fontSize=11).encode(x="x:Q", y=alt.value(10), text="t:N")
    return (barras + reglas + textos).properties(height=250, title="¿Cómo se reparte el riesgo?")


def radar():
    if res is None:
        st.info("No hay tabla de contratos exportada.")
        return
    rad = res[res["prioridad"].notna()].copy()
    rad["prioridad"] = rad["prioridad"].astype(int)
    st.markdown(f"**{miles(len(rad))} contratos asegurables que todavía están en ejecución, ordenados por riesgo de atraso.** "
                "La Directora de Indemnizaciones puede revisar a fondo unos 1.000 al año: los marcados con ⭐ son los "
                "que conviene revisar primero.")
    with st.container(border=True):
        f1, f2, f3, f4 = st.columns([1, 1, 1.4, 1])
        deptos = f1.multiselect("Departamento", sorted(rad["departamento"].dropna().unique()), placeholder="Todos")
        tipos = f2.multiselect("Tipo de contrato", sorted(rad["tipo_de_contrato"].dropna().unique()), placeholder="Todos")
        entidades = f3.multiselect("Entidad", sorted(rad["nombre_entidad"].dropna().unique()), placeholder="Todas")
        decisiones = f4.multiselect("Recomendación", DECISIONES, placeholder="Todas")
        solo_top = st.toggle("Mostrar solo los 1.000 prioritarios (⭐)", value=False)
    vista = rad
    if deptos:
        vista = vista[vista["departamento"].isin(deptos)]
    if tipos:
        vista = vista[vista["tipo_de_contrato"].isin(tipos)]
    if entidades:
        vista = vista[vista["nombre_entidad"].isin(entidades)]
    if decisiones:
        vista = vista[vista["decision"].isin(decisiones)]
    if solo_top:
        vista = vista[vista["prioridad"] <= 1000]
    vista = vista.sort_values("prioridad")
    if vista.empty:
        if solo_top:
            st.warning("Ninguno de los 1.000 contratos prioritarios cumple estos filtros. Apague **Mostrar solo los 1.000 "
                       "prioritarios** para ver todos los contratos en ejecución que sí los cumplen.")
        else:
            st.warning("Ningún contrato en ejecución cumple estos filtros. Quite alguno para ampliar la búsqueda.")
        st.info(AVISO, icon="ℹ️")
        return

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        tarjeta_html("Contratos en la vista", miles(len(vista)), "en ejecución", AZUL)
    with k2:
        tarjeta_html("⭐ Prioritarios", miles((vista["prioridad"] <= 1000).sum()), "entre los 1.000 a revisar", "#6C4AB6")
    with k3:
        pm = vista["probabilidad"].mean()
        tarjeta_html("Riesgo medio", pct(pm), f"promedio general {pct(TASA_PROMEDIO)}", ROJO if pm >= U2 else NARANJA if pm >= U1 else VERDE)
    with k4:
        tarjeta_html("Con garantías", pct((vista["decision"] == DECISIONES[-1]).mean()),
                     f"{miles((vista['decision'] == DECISIONES[-1]).sum())} contratos", ROJO)

    g1, g2 = st.columns([1, 1.8])
    with g1:
        st.markdown("**Recomendación**")
        st.altair_chart(dona(vista["decision"].value_counts().reindex(DECISIONES).dropna()), width="stretch")
    with g2:
        st.altair_chart(histograma(vista), width="stretch")

    mostrar = pd.DataFrame({
        "Prioridad": vista["prioridad"].map(lambda p: f"⭐ {p}" if p <= 1000 else str(p)),
        "Identificador SECOP II": vista["id_contrato"], "Entidad": vista["nombre_entidad"],
        "Departamento": vista["departamento"], "Tipo": vista["tipo_de_contrato"],
        "Probabilidad de atraso": (vista["probabilidad"] * 100).round(1),
        "Recomendación": vista["decision"].map(lambda d: f"{ICONO.get(d, '')} {d}"),
        "Razones principales": vista["razones"].fillna("").map(coma).str.replace(" pts", " puntos")})
    st.markdown("**Lista ordenada por riesgo**")
    st.dataframe(mostrar, hide_index=True, width="stretch", height=430, column_config={
        "Probabilidad de atraso": st.column_config.ProgressColumn(format="%.1f %%", min_value=0, max_value=100)})
    st.download_button("⬇️ Descargar esta lista (CSV)", mostrar.to_csv(index=False).encode("utf-8-sig"),
                       file_name="radar_obrasegura.csv", mime="text/csv")

    b1, b2 = st.columns(2)
    with b1:
        st.altair_chart(barras_apiladas(vista, "nombre_entidad", "Entidades con más contratos en la vista"), width="stretch")
    with b2:
        st.altair_chart(barras_apiladas(vista, "departamento", "Departamentos con más contratos en la vista"), width="stretch")
    st.caption("Organizar la revisión por entidad rinde más: una reunión con la entidad cubre varios contratos de la lista.")
    st.info(AVISO, icon="ℹ️")


# ---------------------------------------------------------------------------------------------
# Pestaña 3: cuánto vale el modelo
# ---------------------------------------------------------------------------------------------
def grafico_intervalo(ahorro, a, b):
    """Ahorro frente a la regla con su intervalo de 95 % y la línea de cero."""
    d = pd.DataFrame({"y": ["Ahorro"], "x": [ahorro], "a": [a], "b": [b]})
    base = alt.Chart(d).encode(y=alt.Y("y:N", title=None, axis=None))
    eje = alt.Scale(domain=[-20, 150])
    return alt.layer(
        alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=ROJO, strokeWidth=2, strokeDash=[4, 3]).encode(
            x=alt.X("x:Q", scale=eje, title="Ahorro frente a la regla (unidades por cada 1.000 contratos)")),
        base.mark_rule(color=AZUL, strokeWidth=8).encode(x=alt.X("a:Q", scale=eje), x2="b:Q"),
        base.mark_point(size=320, filled=True, color=AZUL, opacity=1).encode(x="x:Q"),
        base.mark_text(dy=-24, fontWeight="bold", fontSize=14, color=AZUL).encode(x="x:Q", text=alt.value(miles(ahorro))),
        base.mark_text(dy=22, fontSize=11, color=GRIS).encode(x="a:Q", text=alt.value(miles(a))),
        base.mark_text(dy=22, fontSize=11, color=GRIS).encode(x="b:Q", text=alt.value(miles(b))),
        alt.Chart(pd.DataFrame({"x": [0], "t": ["cero = sin ventaja"]})).mark_text(
            dy=-34, dx=4, align="left", color=ROJO, fontSize=11).encode(x="x:Q", text="t:N"),
    ).properties(height=140, title="¿El ahorro es real? (intervalo de 95 %)")


def grafico_encontrados(encontrados):
    """Atrasos que se encuentran revisando 1.000 contratos: modelo, regla y azar."""
    d = pd.DataFrame({"Método": ["Modelo", "Regla simple", "Al azar"], "Atrasos": [int(v) for v in encontrados]})
    base = alt.Chart(d).encode(x=alt.X("Método:N", sort=None, title=None, axis=alt.Axis(labelAngle=0, labelFontSize=12)),
                               y=alt.Y("Atrasos:Q", title="Atrasos encontrados", scale=alt.Scale(domain=[0, 620])))
    barras = base.mark_bar(cornerRadiusEnd=4, size=56).encode(
        color=alt.Color("Método:N", scale=alt.Scale(domain=list(d["Método"]), range=[VERDE, GRIS, "#C8CCD0"]), legend=None))
    return (barras + base.mark_text(dy=-9, fontWeight="bold", fontSize=13).encode(text="Atrasos:Q")).properties(
        height=210, title="Revisando 1.000 contratos, ¿cuántos atrasos encuentra?")


def grafico_importancia():
    d = pd.DataFrame(IMPORTANCIA, columns=["Característica", "Importancia"])
    d["Quién"] = d["Característica"].map(lambda x: "Entidad" if ("entidad" in x.lower() or x == "Departamento") else
                                         "Contratista" if "contratista" in x.lower() else "Contrato")
    return alt.Chart(d).mark_bar(cornerRadiusEnd=4).encode(
        y=alt.Y("Característica:N", sort=None, title=None, axis=alt.Axis(labelLimit=300)),
        x=alt.X("Importancia:Q", title="Cuánto empeora el modelo si se desordena (caída del AUC)"),
        color=alt.Color("Quién:N", scale=alt.Scale(domain=["Entidad", "Contrato", "Contratista"], range=[ROJO, AZUL, GRIS]),
                        legend=alt.Legend(orient="top", title=None))).properties(height=300, title="¿Qué mira el modelo?")


def valor():
    ahorro = m["costo_regla"] - m["costo_modelo"]
    st.markdown("**¿Vale la pena usar el modelo en lugar de la regla del suscriptor?** Se midió en los "
                f"{miles(17183)} contratos firmados en 2024 y 2025, que el modelo nunca vio y cuyo desenlace ya se conoce.")
    c1, c2, c3 = st.columns(3)
    with c1:
        tarjeta_html("Costo con el modelo", miles(m["costo_modelo"]), "unidades por cada 1.000 contratos", VERDE)
    with c2:
        tarjeta_html("Costo con la regla simple", miles(m["costo_regla"]), "lo que haría el suscriptor sin modelo", GRIS)
    with c3:
        tarjeta_html("Ahorro del modelo", miles(ahorro),
                     f"{ahorro / m['costo_regla']:.0%} menos costo que la regla".replace("%", " %"), AZUL)

    g1, g2 = st.columns([1.3, 1])
    with g1:
        comp = pd.DataFrame({"Decisión": ["Modelo", "Recargo a todos", "Regla simple", "Tarifa estándar a todos"],
                             "Costo": [m["costo_modelo"], m.get("Costo de cobrar recargo a todos"), m["costo_regla"],
                                       m.get("Costo de tarifa estándar a todos")]}).dropna()
        comp["Grupo"] = comp["Decisión"].map(lambda d: "Modelo" if d == "Modelo" else "Sin modelo")
        comp["Etiqueta"] = comp["Costo"].map(miles)
        base = alt.Chart(comp).encode(
            y=alt.Y("Decisión:N", sort=list(comp["Decisión"]), title=None, axis=alt.Axis(labelLimit=260, labelFontSize=12)),
            x=alt.X("Costo:Q", title="Costo por cada 1.000 contratos (menos es mejor)", axis=alt.Axis(format="d"),
                    scale=alt.Scale(domain=[0, 1300])))
        barras = base.mark_bar(cornerRadiusEnd=4, height=30).encode(
            color=alt.Color("Grupo:N", scale=alt.Scale(domain=["Modelo", "Sin modelo"], range=[VERDE, GRIS]), legend=None))
        textos = base.mark_text(align="left", dx=6, fontSize=13, fontWeight="bold").encode(text="Etiqueta:N")
        st.altair_chart((barras + textos).properties(height=210, title="Costo de los errores"), width="stretch")
    with g2:
        if "intervalo_diferencia" in m:
            st.altair_chart(grafico_intervalo(ahorro, *m["intervalo_diferencia"]), width="stretch")
            st.caption("El intervalo completo está lejos del cero: la ventaja del modelo no es suerte.")
        encontrados = str(m.get("Atrasos encontrados al revisar 1.000 (modelo / regla / azar)", "")).split(" / ")
        if len(encontrados) == 3:
            st.altair_chart(grafico_encontrados(encontrados), width="stretch")
    st.markdown(f"""
**Cómo leerlo.** Cada error le cuesta a Cimiento: **5 unidades** si cobra tarifa estándar a un contrato que después se atrasa
(más seguimiento, reclamaciones y provisiones) y **1 unidad** si cobra recargo a uno que no se atrasa (el cliente puede irse
a otra aseguradora). Una unidad equivale más o menos a un cliente perdido por un recargo que no merecía.

- **Regla simple** (lo que haría un suscriptor sin modelo): *{m['regla_simple'].replace('.', ',')}*.
- **Cobrarle tarifa estándar a todos** es lo más caro: uno de cada cuatro contratos de 2024–2025 se atrasó.
- **Cobrarle recargo a todos** cuesta menos, pero castiga a todos los buenos clientes. El modelo cuesta menos que eso y
  le cobra recargo solo al {m.get('% de contratos con recargo (modelo)', '39 %')} de los contratos.
""")
    st.caption("Supuesto del equipo para pasarlo a pesos: si una unidad ≈ una prima típica (1 % del 10 % asegurado del valor "
               "mediano, unos $217.000), el ahorro frente a la regla es de unos $23 millones por cada 1.000 pólizas. "
               "La cifra depende del supuesto de prima.")
    st.warning("**Límite:** el modelo se entrenó con contratos de 2020–2023 y subestima el riesgo reciente. En 2025 no le "
               "ganó a cobrarle recargo a todos. Antes de usarlo en producción debe recalibrarse con 2024–2025.")


# ---------------------------------------------------------------------------------------------
# Pestaña 4: cómo decide
# ---------------------------------------------------------------------------------------------
def como_decide():
    st.markdown("**De la probabilidad a la recomendación**")
    st.altair_chart(barra_riesgo(alto=80), width="stretch")
    c = st.columns(3)
    rangos = [f"menos de {pct(U1)}", f"de {pct(U1)} a {pct(U2)}", f"{pct(U2)} o más"]
    for col, d, rg in zip(c, DECISIONES, rangos):
        with col:
            tarjeta_html(rg, f"{ICONO[d]} {d}", QUE_HACER[d], COLOR[d])

    g1, g2 = st.columns([1, 1.5])
    with g1:
        if res is not None:
            prueba = res[res["prioridad"].isna()]
            st.markdown("**Así se repartirían las pólizas** (contratos de prueba 2024–2025)")
            st.altair_chart(dona(prueba["decision"].value_counts().reindex(DECISIONES).dropna()), width="stretch")
    with g2:
        st.altair_chart(grafico_importancia(), width="stretch")

    st.markdown(f"""
- **¿Por qué {pct(U1)} y no 50 %?** Dejar pasar un atraso cuesta cinco veces más que un recargo innecesario, así que conviene
  cobrar recargo desde una probabilidad baja. El {pct(U1)} es el umbral que dio el menor costo en la validación 2022–2023.
- **¿Por qué garantías desde {pct(U2)}?** Es el corte del 10 % de contratos de mayor riesgo: la capacidad del área para pedir
  codeudor o contragarantía. En la prueba ese grupo se atrasó cerca del 49 %, más del doble del promedio.
- **Pesa más quién contrata que quién ejecuta:** la historia de atrasos de la **entidad** es lo que más usa el modelo; la del
  contratista casi no pesa. Le siguen el valor, el plazo, el tipo de obra y la firma a fin de año.
- **¿Y las interventorías?** Su tasa de atraso subió a 37 % en 2024–2025. Recomendamos cobrarles recargo a todas aunque el modelo
  diga tarifa estándar.
""")
    st.caption(f"Modelo: {m.get('Modelo', '')}. Entrenado con {miles(meta['n_entrenamiento'])} contratos firmados entre 2020 y "
               f"2023; exportado el {meta['fecha_exportacion'][:10]}. La importancia de variables viene del cuaderno del "
               "equipo y no es causal: dice qué usa el modelo, no qué pasaría si algo cambiara.")
    st.info(AVISO, icon="ℹ️")


# ---------------------------------------------------------------------------------------------
# Cuerpo
# ---------------------------------------------------------------------------------------------
if config["interfaz"] == "html":
    from core.web import construir_html
    st.iframe(construir_html(), height=820)
    with st.expander(f"Evaluar {config['unidad']} nuevo"):
        nuevo()
else:
    pestanas = st.tabs(["🔎 Evaluar un contrato", "📡 Radar de contratos en ejecución", "💰 Cuánto vale el modelo",
                        "⚙️ Cómo decide"])
    with pestanas[0]:
        modo = st.radio("¿Qué quiere hacer?", ["Buscar un contrato por su identificador",
                                               "Evaluar un contrato nuevo (escribir sus datos)"], horizontal=True)
        if modo.startswith("Buscar"):
            buscar()
        else:
            nuevo()
    with pestanas[1]:
        radar()
    with pestanas[2]:
        valor()
    with pestanas[3]:
        como_decide()

# Pie de página: debe quedar (atribuciones y advertencias del caso, en mi_app.py)
st.divider()
st.caption(config["pie"])
