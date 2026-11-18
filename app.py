"""ZONA LIBRE: la interfaz de ObraSegura para Cimiento Seguros.
Usa solo las funciones de la zona fija (core/). El pie de página (config["pie"]) debe quedar al final.

Para verla en su computador:   streamlit run app.py"""
import re

import pandas as pd
import streamlit as st

from core import (cargar_config, cargar_metadata, cargar_modelo, cargar_resultados, etiqueta, evaluar,
                  hay_modelo, texto_razon, validar)

config = cargar_config()
st.set_page_config(page_title=config["titulo"], page_icon="🛡️", layout="wide")

AVISO = ("La probabilidad es una **estimación de riesgo** basada en contratos anteriores, no una prueba de que la "
         "entidad o el contratista hayan hecho algo mal.")
QUE_HACER = {
    "Tarifa estándar": "Expedir la póliza con la tarifa estándar.",
    "Recargo": "Expedir la póliza con recargo.",
    "Recargo + garantías": "Expedir con recargo y exigir garantías adicionales (contragarantía o codeudor). "
                           "Está entre el 10 % de mayor riesgo.",
}
COLOR = {"Tarifa estándar": "green", "Recargo": "orange", "Recargo + garantías": "red"}
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


def coma(texto):
    """Decimales con coma: '41.6 puntos' → '41,6 puntos'."""
    return re.sub(r"(\d)\.(\d+) (pts|puntos)", r"\1,\2 \3", str(texto))


def pct(p):
    return f"{p:.0%}".replace("%", " %")


def miles(x):
    return f"{x:,.0f}".replace(",", ".")


# ---------------------------------------------------------------------------------------------
# Encabezado
# ---------------------------------------------------------------------------------------------
col_logo, col_titulo = st.columns([1, 6])
with col_logo:
    try:
        st.image(config["logo"], width=120)
    except Exception:
        st.markdown("# 🛡️")
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


def tarjeta(probabilidad, decision, razones, tipo=None):
    """Cómo se ve la evaluación de un contrato."""
    c1, c2 = st.columns([1, 2])
    c1.metric("Probabilidad de atraso", pct(probabilidad),
              help="Probabilidad de que los días añadidos con prórrogas superen el 20 % del plazo pactado.")
    with c2:
        st.markdown(f"**Recomendación:** :{COLOR.get(decision, 'gray')}[**{decision}**]")
        st.markdown(QUE_HACER.get(decision, ""))
    if tipo == "Interventoría" and decision == "Tarifa estándar":
        st.warning("**Salvaguarda de interventorías:** las interventorías se atrasan cada vez más (37 % en 2024–2025) y "
                   "ahí el modelo se queda corto. La política recomendada es cobrarles recargo a todas.")
    st.markdown("**Por qué (razones principales)**")
    if not razones:
        st.caption("Con estos valores ninguna variable mueve la probabilidad frente a un contrato típico.")
    for r in razones:
        st.markdown(f"- {coma(texto_razon(r, meta) if isinstance(r, dict) else r)}")
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
        st.caption(f"La lista tiene {miles(len(res))} contratos: {miles((~res['prioridad'].isna()).sum())} en ejecución "
                   f"(radar) y {miles(res['prioridad'].isna().sum())} de prueba 2024–2025 ya terminados.")
        return
    f = res[res["id_contrato"] == elegido].iloc[0]
    st.markdown(f"**{f['nombre_entidad']}** · {f['departamento']} · {f['tipo_de_contrato']} · {f['modalidad']}  \n"
                f"*{f['conjunto']}*" + (f" · prioridad **{int(f['prioridad'])}** en el radar"
                                        if pd.notna(f["prioridad"]) else ""))
    razones = [x for x in str(f.get("razones", "")).split(" · ") if x and x != "nan"]
    razones = [x.replace(" pts", " puntos").replace(" sube ", " sube la probabilidad ").replace(" baja ", " baja la probabilidad ")
               for x in razones]
    tarjeta(float(f["probabilidad"]), f["decision"], razones, f["tipo_de_contrato"])


def campo(col):
    nombre, texto = col["nombre"], etiqueta(meta, col["nombre"])
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
def radar():
    if res is None:
        st.info("No hay tabla de contratos exportada.")
        return
    rad = res[res["prioridad"].notna()].copy()
    rad["prioridad"] = rad["prioridad"].astype(int)
    st.markdown(f"**{miles(len(rad))} contratos asegurables que todavía están en ejecución, ordenados por riesgo de atraso.** "
                "La Directora de Indemnizaciones puede revisar a fondo unos 1.000 al año: los marcados con ⭐ son los "
                "que conviene revisar primero.")
    f1, f2, f3, f4 = st.columns([1, 1, 1.4, 1])
    deptos = f1.multiselect("Departamento", sorted(rad["departamento"].dropna().unique()), placeholder="Todos")
    tipos = f2.multiselect("Tipo de contrato", sorted(rad["tipo_de_contrato"].dropna().unique()), placeholder="Todos")
    entidades = f3.multiselect("Entidad", sorted(rad["nombre_entidad"].dropna().unique()), placeholder="Todas")
    decisiones = f4.multiselect("Recomendación", meta["decisiones"], placeholder="Todas")
    solo_top = st.toggle("Solo los 1.000 prioritarios", value=True)
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

    k1, k2, k3 = st.columns(3)
    k1.metric("Contratos en la vista", miles(len(vista)))
    k2.metric("Entre los 1.000 prioritarios", miles((vista["prioridad"] <= 1000).sum()))
    k3.metric("Probabilidad media de atraso", pct(vista["probabilidad"].mean()) if len(vista) else "—")

    mostrar = pd.DataFrame({
        "Prioridad": vista["prioridad"].map(lambda p: f"⭐ {p}" if p <= 1000 else str(p)),
        "Identificador SECOP II": vista["id_contrato"], "Entidad": vista["nombre_entidad"],
        "Departamento": vista["departamento"], "Tipo": vista["tipo_de_contrato"],
        "Probabilidad de atraso": (vista["probabilidad"] * 100).round(1), "Recomendación": vista["decision"],
        "Razones principales": vista["razones"].fillna("").map(coma).str.replace(" pts", " puntos")})
    st.dataframe(mostrar, hide_index=True, width="stretch", height=430, column_config={
        "Probabilidad de atraso": st.column_config.ProgressColumn(format="%.1f %%", min_value=0, max_value=100)})
    st.download_button("Descargar esta lista (CSV)", mostrar.to_csv(index=False).encode("utf-8-sig"),
                       file_name="radar_obrasegura.csv", mime="text/csv")

    if len(vista):
        st.markdown("**Entidades con más contratos en esta vista.** Organizar la revisión por entidad rinde más: "
                    "una reunión con la entidad cubre varios contratos de la lista.")
        top = vista["nombre_entidad"].value_counts().head(10).rename("Contratos")
        st.bar_chart(top, horizontal=True, height=320)
    st.info(AVISO, icon="ℹ️")


# ---------------------------------------------------------------------------------------------
# Pestaña 3: cuánto vale el modelo
# ---------------------------------------------------------------------------------------------
def valor():
    ahorro = m["costo_regla"] - m["costo_modelo"]
    st.markdown("**¿Vale la pena usar el modelo en lugar de la regla del suscriptor?** Se midió en los "
                f"{miles(17183)} contratos firmados en 2024 y 2025, que el modelo nunca vio y cuyo desenlace ya se conoce.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Costo con el modelo", miles(m["costo_modelo"]), help="Unidades de costo por cada 1.000 contratos.")
    c2.metric("Costo con la regla simple", miles(m["costo_regla"]))
    c3.metric("Ahorro del modelo", miles(ahorro), delta=f"−{ahorro / m['costo_regla']:.0%} frente a la regla".replace("%", " %"),
              delta_color="inverse")
    if "intervalo_diferencia" in m:
        a, b = m["intervalo_diferencia"]
        st.caption(f"Con 95 % de confianza, el ahorro está entre {miles(a)} y {miles(b)} unidades por cada 1.000 contratos: "
                   "el intervalo no toca el cero, así que la ventaja no es suerte.")
    comp = pd.DataFrame({"Costo por 1.000 contratos": {
        "Modelo": m["costo_modelo"], "Regla simple": m["costo_regla"],
        "Recargo a todos": m.get("Costo de cobrar recargo a todos"),
        "Tarifa estándar a todos": m.get("Costo de tarifa estándar a todos")}}).dropna()
    st.bar_chart(comp, horizontal=True, height=230)
    st.markdown(f"""
**Cómo leerlo.** Cada error le cuesta a Cimiento: **5 unidades** si cobra tarifa estándar a un contrato que después se atrasa
(más seguimiento, reclamaciones y provisiones) y **1 unidad** si cobra recargo a uno que no se atrasa (el cliente puede irse
a otra aseguradora). Una unidad equivale más o menos a un cliente perdido por un recargo que no merecía.

- **Regla simple** (lo que haría un suscriptor sin modelo): *{m['regla_simple'].replace('.', ',')}*.
- **Cobrarle tarifa estándar a todos** es lo más caro: uno de cada cuatro contratos de 2024–2025 se atrasó.
- **Cobrarle recargo a todos** cuesta menos, pero castiga a todos los buenos clientes. El modelo cuesta menos que eso y
  le cobra recargo solo al {m.get('% de contratos con recargo (modelo)', '39 %')} de los contratos.
- **Seguimiento:** revisando 1.000 contratos, el modelo encuentra {m.get('Atrasos encontrados al revisar 1.000 (modelo / regla / azar)', '').split(' / ')[0]}
  atrasos, contra {m.get('Atrasos encontrados al revisar 1.000 (modelo / regla / azar)', ' / 320').split(' / ')[1]} con la regla
  y {m.get('Atrasos encontrados al revisar 1.000 (modelo / regla / azar)', ' /  / 229').split(' / ')[2]} al azar.
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
    st.table(pd.DataFrame({
        "Probabilidad de atraso": [f"menos de {pct(U1)}", f"de {pct(U1)} a {pct(U2)}", f"{pct(U2)} o más"],
        "Recomendación": meta["decisiones"],
        "Qué hace Cimiento": [QUE_HACER[d] for d in meta["decisiones"]]}))
    st.markdown(f"""
- **¿Por qué {pct(U1)} y no 50 %?** Dejar pasar un atraso cuesta cinco veces más que un recargo innecesario, así que conviene
  cobrar recargo desde una probabilidad baja. El {pct(U1)} es el umbral que dio el menor costo en la validación 2022–2023.
- **¿Por qué garantías desde {pct(U2)}?** Es el corte del 10 % de contratos de mayor riesgo: la capacidad del área para pedir
  codeudor o contragarantía. En la prueba ese grupo se atrasó cerca del 49 %, más del doble del promedio.
- **¿Qué mira el modelo?** Sobre todo la **historia de atrasos de la entidad que contrata** (pesa más quién contrata que quién
  ejecuta), el valor y el plazo, el tipo de obra (las interventorías se atrasan más) y la firma a fin de año.
- **¿Y las interventorías?** Su tasa de atraso subió a 37 % en 2024–2025. Recomendamos cobrarles recargo a todas aunque el modelo
  diga tarifa estándar.
""")
    st.caption(f"Modelo: {m.get('Modelo', '')}. Entrenado con {miles(meta['n_entrenamiento'])} contratos firmados entre 2020 y "
               f"2023; exportado el {meta['fecha_exportacion'][:10]}.")
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
