"""ZONA LIBRE: la interfaz de la aplicación.
Ya funciona con cualquier modelo exportado con exportar.py. Desde aquí la adaptan a su caso:
cambien textos, orden, gráficos y colores, con ayuda de IA si quieren (PASO 5 de la guía).
Lo único que debe quedar es el pie de página al final.

Para verla en su computador:   streamlit run app.py"""
import pandas as pd
import streamlit as st

from core import (cargar_config, cargar_metadata, cargar_modelo, cargar_resultados, etiqueta, evaluar,
                  hay_modelo, texto_razon, validar)

config = cargar_config()
st.set_page_config(page_title=config["titulo"], layout="wide")


# ---------------------------------------------------------------------------------------------
# Encabezado: título, cliente y descripción vienen de mi_app.py
# ---------------------------------------------------------------------------------------------
col_logo, col_titulo = st.columns([1, 5])
with col_logo:
    try:
        st.image(config["logo"], width=150)
    except Exception:
        pass
with col_titulo:
    st.title(config["titulo"])
    st.caption(f"{config['cliente']} · {config['descripcion']}")


# ---------------------------------------------------------------------------------------------
# Mientras no exporten su modelo, la app muestra la guía en lugar de fallar
# ---------------------------------------------------------------------------------------------
if not hay_modelo():
    st.info("Todavía no hay modelo en la carpeta model/. Sigan la guía del README:")
    st.markdown("""
1. Entrenen su modelo como un `Pipeline` de scikit-learn.
2. Expórtenlo con `exportar` (en Colab, cuaderno `Exportar_modelo_desde_Colab.ipynb`).
3. Completen `mi_app.py`.
4. Corran `desplegar` (en Colab, `Desplegar_desde_Colab.ipynb`; en su computador, `python desplegar.py`).
5. Adapten esta interfaz a su caso.
""")
    st.divider()
    st.caption(config["pie"])
    st.stop()


@st.cache_resource
def recursos():
    return cargar_metadata(), cargar_modelo(), cargar_resultados()


meta, modelo, resultados = recursos()
evento = meta["evento"]
unidad = config["unidad"]


def mostrar_resultado(probabilidad, decision, razones):
    """Cómo se ve el resultado de una evaluación. Cambien el formato si quieren."""
    c1, c2 = st.columns(2)
    c1.metric(f"Probabilidad de {evento}", f"{probabilidad:.0%}")
    c2.metric("Recomendación", decision)
    if not razones:
        st.caption("Con estos valores ninguna variable mueve la probabilidad frente a un caso típico.")
    else:
        st.markdown("**Razones principales**")
        for r in razones:
            if isinstance(r, dict):
                st.markdown(f"- {texto_razon(r, meta)}")
            else:
                st.markdown(f"- {r}")
        st.caption("Las razones muestran de qué depende la predicción del modelo, no qué pasaría si algo cambiara.")


def formulario_nuevo():
    """Un campo por cada variable de entrada del modelo, con valores típicos por defecto."""
    valores = {}
    with st.form("nuevo"):
        columnas = st.columns(2)
        for i, col in enumerate(meta["columnas"]):
            nombre = col["nombre"]
            texto = etiqueta(meta, nombre)
            with columnas[i % 2]:
                if col["tipo"] == "numérica":
                    valores[nombre] = st.number_input(texto, value=float(col["referencia"]), key=nombre)
                elif col["tipo"] == "categórica":
                    valores[nombre] = st.selectbox(texto, col.get("categorias") or [""], key=nombre)
                else:
                    valores[nombre] = st.text_area(texto, key=nombre)
        enviado = st.form_submit_button("Evaluar")
    if enviado:
        datos, errores, avisos = validar(pd.DataFrame([valores]), meta)
        for e in errores:
            st.error(e)
        for a in avisos:
            st.warning(a)
        if not errores:
            r = evaluar(modelo, meta, datos)[0]
            mostrar_resultado(r["probabilidad"], r["decision"], r["razones"])


def buscar_en_lista():
    col_id = meta.get("columna_id")
    if resultados is None or not col_id or col_id not in resultados.columns:
        st.info("No exportaron una tabla de resultados con columna_id para buscar.")
        return
    elegido = st.selectbox(f"Busquen {unidad} por {etiqueta(meta, col_id)}", resultados[col_id].astype(str))
    fila = resultados[resultados[col_id].astype(str) == elegido].iloc[0]
    razones = [r for r in str(fila.get("razones", "")).split(" · ") if r and r != "nan"]
    mostrar_resultado(float(fila["probabilidad"]), fila["decision"], razones)


def vista_lista():
    if resultados is None:
        st.info("Exporten una tabla de resultados (tabla_resultados en exportar) para ver aquí la lista.")
        return
    decisiones = st.multiselect("Recomendación", meta["decisiones"], default=meta["decisiones"])
    tabla = resultados[resultados["decision"].isin(decisiones)].sort_values("probabilidad", ascending=False)
    st.write(f"{len(tabla)} filas")
    if {"lat", "lon"}.issubset(tabla.columns):
        colores = ["#2E7D32", "#F9A825", "#C62828", "#6A1B9A"]
        mapa = tabla[["lat", "lon", "decision"]].copy()
        mapa["color"] = [colores[meta["decisiones"].index(d) % len(colores)] for d in mapa["decision"]]
        st.map(mapa, latitude="lat", longitude="lon", color="color", size=40)
    st.dataframe(tabla, width="stretch", hide_index=True)


def vista_valor():
    m = meta["metricas"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Costo con el modelo", f"{m['costo_modelo']:,.0f}".replace(",", "."))
    c2.metric("Costo con la regla simple", f"{m['costo_regla']:,.0f}".replace(",", "."))
    c3.metric("Ahorro frente a la regla", f"{m['costo_regla'] - m['costo_modelo']:,.0f}".replace(",", "."))
    st.caption(f"Costos {m['unidad_costo']}, en los datos de prueba.")
    st.markdown(f"**Regla simple:** {m['regla_simple']}")
    if "intervalo_diferencia" in m:
        a, b = m["intervalo_diferencia"]
        st.markdown(f"Intervalo de 95 % del ahorro: de {a:,.0f} a {b:,.0f}".replace(",", "."))
    otras = {k: v for k, v in m.items()
             if k not in ("costo_modelo", "costo_regla", "regla_simple", "unidad_costo", "intervalo_diferencia")}
    if otras:
        st.table(pd.DataFrame({"Métrica": list(otras.keys()), "Valor": [str(v) for v in otras.values()]}))


def vista_regla():
    filas = []
    limites = [0.0] + meta["umbrales"] + [1.0]
    for i, d in enumerate(meta["decisiones"]):
        filas.append({f"Probabilidad de {evento}": f"{limites[i]:.0%} a {limites[i + 1]:.0%}", "Recomendación": d})
    st.table(pd.DataFrame(filas))
    st.caption(f"Modelo entrenado con {meta['n_entrenamiento']} filas; exportado el {meta['fecha_exportacion']}.")


# ---------------------------------------------------------------------------------------------
# Cuerpo de la app. PASO 5: adapten pestañas, textos y gráficos a lo que necesita su cliente.
# ---------------------------------------------------------------------------------------------
if config["interfaz"] == "html":
    from core.web import construir_html
    st.iframe(construir_html(), height=820)
    with st.expander(f"Evaluar {unidad} nuevo"):
        formulario_nuevo()
else:
    pestanas = st.tabs([f"Evaluar {unidad}", "Lista", "Cuánto vale el modelo", "Cómo decide"])
    with pestanas[0]:
        modo = st.radio("¿Qué quieren hacer?", ["Escribir los datos", "Buscar en la lista"], horizontal=True)
        if modo == "Escribir los datos":
            formulario_nuevo()
        else:
            buscar_en_lista()
    with pestanas[1]:
        vista_lista()
    with pestanas[2]:
        vista_valor()
    with pestanas[3]:
        vista_regla()


# Pie de página: debe quedar (atribuciones y advertencias de su caso, en mi_app.py)
st.divider()
st.caption(config["pie"])
