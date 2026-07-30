from datetime import datetime
import json
import os
from fpdf import FPDF
import requests
import streamlit as st

# ==========================================
# 1. FUNZIONI DI SUPPORTO E PULIZIA
# ==========================================
FILE_CRONOLOGIA = "cronologia.json"


def pulisci(testo):
    """Pulisce i testi per evitare crash del PDF a causa di accenti o caratteri speciali in latin-1."""
    if testo is None:
        return ""
    testo = str(testo).replace("€", "EUR").replace("°", " deg.")
    sostituzioni = {
        "à": "a'",
        "è": "e'",
        "é": "e'",
        "ì": "i'",
        "ò": "o'",
        "ù": "u'",
        "À": "A'",
        "È": "E'",
        "Ì": "I'",
        "Ò": "O'",
        "Ù": "U'",
    }
    for orig, sost in sostituzioni.items():
        testo = testo.replace(orig, sost)
    return testo.encode("latin-1", "replace").decode("latin-1")


def carica_cronologia():
    if os.path.exists(FILE_CRONOLOGIA):
        with open(FILE_CRONOLOGIA, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def salva_cronologia(azione, cliente, dettaglio, importo="-"):
    storico = carica_cronologia()
    nuovo_record = {
        "Data": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "Azione": azione,
        "Cliente": cliente,
        "Dettaglio": dettaglio,
        "Importo": importo,
    }
    storico.insert(0, nuovo_record)
    with open(FILE_CRONOLOGIA, "w", encoding="utf-8") as f:
        json.dump(storico, f, indent=4, ensure_ascii=False)


# ==========================================
# 2. API GRATUITA PER CALCOLO PERCORSI
# ==========================================
def calcola_distanza_api(partenza, arrivo):
    headers = {"User-Agent": "TruckApp/1.0"}
    try:
        # 1. Trova coordinate partenza
        res_p = requests.get(
            f"https://nominatim.openstreetmap.org/search?q={partenza}&format=json&limit=1",
            headers=headers,
        ).json()
        # 2. Trova coordinate arrivo
        res_a = requests.get(
            f"https://nominatim.openstreetmap.org/search?q={arrivo}&format=json&limit=1",
            headers=headers,
        ).json()

        if res_p and res_a:
            lat1, lon1 = res_p[0]["lat"], res_p[0]["lon"]
            lat2, lon2 = res_a[0]["lat"], res_a[0]["lon"]
            # 3. Calcola i KM reali di guida
            url_route = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
            res_route = requests.get(url_route).json()
            km = round(res_route["routes"][0]["distance"] / 1000.0, 1)
            # Calcolo pedaggio stimato per camion (circa 0.17€ al km)
            pedaggio = round((km * 0.80) * 0.17, 2)
            return km, pedaggio
    except Exception:
        return None, None
    return None, None


# ==========================================
# 3. CLASSE PDF AVANZATA (MODELLO GRAFICO)
# ==========================================
class MioPDF(FPDF):

    def disegna_cella_sezione(self, x, y, w, h, titolo, valore="", bg_hdr=True):
        """Disegna una cella strutturata con intestazione grigia ed etichetta in evidenza."""
        # Rettangolo esterno della cella
        self.set_line_width(0.3)
        self.set_draw_color(60, 60, 60)
        self.rect(x, y, w, h)

        # Barra di intestazione cella
        if bg_hdr:
            self.set_fill_color(240, 242, 245)
            self.rect(x, y, w, 5, "F")
            self.line(x, y + 5, x + w, y + 5)

        # Testo Intestazione
        self.set_xy(x + 1.5, y + 0.8)
        self.set_font("Helvetica", "B", 6.5)
        self.set_text_color(50, 50, 50)
        self.cell(w - 3, 3.5, pulisci(titolo.upper()), ln=0)

        # Contenuto Valore
        if valore:
            self.set_xy(x + 2, y + 5.5)
            self.set_font("Helvetica", "B", 8.5)
            self.set_text_color(0, 0, 0)
            # Gestione eventuale testo multilinea
            self.multi_cell(
                w - 4, 3.8, pulisci(valore), border=0, align="L"
            )


def crea_pdf_bolla(dati):
    pdf = MioPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(10, 10, 10)
    pdf.add_page()
    pdf.set_auto_page_break(False)

    # ---------------------------------------------------------
    # INTESTAZIONE PRINCIPALE DOCUMENTO
    # ---------------------------------------------------------
    pdf.set_fill_color(26, 82, 118)  # Blu Scuro Elegante
    pdf.rect(10, 10, 190, 16, "F")

    pdf.set_xy(12, 12)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(100, 6, pulisci(dati["vettore"]), ln=0, align="L")

    pdf.set_xy(110, 12)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(88, 6, "LETTERA DI VETTURA / BOLLA", ln=1, align="R")

    pdf.set_xy(12, 18.5)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(100, 5, "DOCUMENTO DI TRASPORTO MERCI SU STRADA", ln=0, align="L")

    pdf.set_xy(110, 18.5)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(
        88,
        5,
        pulisci(f"N. {dati['num_doc']}  |  Data: {dati['data']}"),
        ln=1,
        align="R",
    )

    # ---------------------------------------------------------
    # SCHEMA E GRIGLIA PRINCIPALE (Y: 28 -> 192)
    # ---------------------------------------------------------
    # Riga 1: Dati Operativi Generali (Y=28, H=12)
    pdf.disegna_cella_sezione(
        10, 28, 45, 12, "Data e Ora Ritiro", f"{dati['data']} - {dati['ora']}"
    )
    pdf.disegna_cella_sezione(
        55, 28, 45, 12, "Riferimento Doc.", dati.get("rif", "N/A")
    )
    pdf.disegna_cella_sezione(
        100, 28, 45, 12, "Compagnia Navale", dati.get("compagnia", "N/A")
    )
    pdf.disegna_cella_sezione(
        145, 28, 55, 12, "Booking / Riferimento", dati.get("booking", "N/A")
    )

    # Riga 2: Committente vs Vettore (Y=41, H=22)
    pdf.disegna_cella_sezione(
        10, 41, 93, 22, "1. Committente / Mittente", dati["committente"]
    )
    pdf.disegna_cella_sezione(
        103, 41, 97, 22, "2. Vettore / Trasportatore", dati["vettore"]
    )

    # Riga 3: Ritiro vs Autista & Mezzi (Y=64, H=22)
    pdf.disegna_cella_sezione(
        10,
        64,
        93,
        22,
        "3. Luogo di Carico / Terminal Ritiro",
        dati["ritiro"],
    )
    info_mezzo = (
        f"Autista: {dati['autista']}\n"
        f"Trattore: {dati['trattore']}  |  Rimorchio: {dati['rimorchio']}"
    )
    pdf.disegna_cella_sezione(
        103, 64, 97, 22, "4. Conducente & Automezzo", info_mezzo
    )

    # Riga 4: Scarico vs Dettagli Container (Y=87, H=22)
    pdf.disegna_cella_sezione(
        10, 87, 93, 22, "5. Luogo di Consegna / Scarico", dati["scarico"]
    )
    info_cnt = (
        f"Sigla/N° Container: {dati['container']}\n"
        f"Peso Lordo (Kg): {dati['peso']}"
    )
    pdf.disegna_cella_sezione(
        103, 87, 97, 22, "6. Identificativo Container & Peso", info_cnt
    )

    # Riga 5: Descrizione Merce (Y=110, H=20)
    pdf.disegna_cella_sezione(
        10,
        110,
        190,
        20,
        "7. Natura della Merce e Tipologia Imballo",
        dati["merce"],
    )

    # Riga 6: Note e Osservazioni di Viaggio (Y=131, H=22)
    pdf.disegna_cella_sezione(
        10,
        131,
        190,
        22,
        "8. Note operative / Riserve del Vettore all'Atto del Carico",
        dati["note"],
    )

    # ---------------------------------------------------------
    # DIRETTIVE SOTTO LO SCHEMA & CONDIZIONI DI TRASPORTO (Y: 155 -> 240)
    # ---------------------------------------------------------
    pdf.set_fill_color(245, 245, 245)
    pdf.rect(10, 155, 190, 80)
    pdf.set_line_width(0.3)
    pdf.rect(10, 155, 190, 80)

    # Titolo Sezione Direttive
    pdf.set_xy(13, 157)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(26, 82, 118)
    pdf.cell(
        184,
        4,
        pulisci("DIRETTIVE, ISTRUZIONI DI TRASPORTO E CONDIZIONI GENERALI"),
        ln=1,
    )
    pdf.line(13, 162, 197, 162)

    # Testo delle Direttive Operative e Legali
    pdf.set_font("Helvetica", "", 6.8)
    pdf.set_text_color(40, 40, 40)

    direttive_testo = (
        "1. NORMATIVA APPLICABILE: Il presente trasporto e' regolato dalle norme del Codice Civile italiano (Art. 1696 e succ.) "
        "e, per i trasporti internazionali, dalla Convenzione relativo al contratto di trasporto internazionale di merci su strada (CMR).\n"
        "2. ISTRUZIONI DI SICUREZZA: Il conducente e' tenuto a verificare l'integrita' dei sigilli e la corrispondenza dei contrassegni. "
        "Eventuali anomalie all'atto del carico devono essere annotate al punto 8 prima della partenza.\n"
        "3. SOSTE E PERCORSI: Il trasporto deve avvenire nel rispetto dei tempi di guida e di riposo previsti dal Regolamento CE 561/2006. "
        "E' fatto divieto assoluto di sosta in aree non custodite o non autorizzate per i carichi sottoposti a vincolo doganale.\n"
        "4. RESA E CONSEGNA: La merce viaggia a rischio del committente salvo i casi di responsabilita' imputabile al vettore ai sensi di legge. "
        "La merce si intende consegnata nello stato in cui si trova, con riserva di riscontro entro i termini stabiliti."
    )

    pdf.set_xy(13, 164)
    pdf.multi_cell(184, 3.2, pulisci(direttive_testo), border=0, align="J")

    # Spazio Direttive Specifiche del Committente (Se presenti)
    pdf.set_xy(13, 202)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(
        184,
        4,
        pulisci(
            "PRESCAIZIONI PARTICOLARI DEL COMMITTENTE / ISTRUZIONI ACCESSORIE:"
        ),
        ln=1,
    )

    pdf.set_font("Helvetica", "I", 7)
    pdf.set_xy(13, 207)
    istruzioni_extra = (
        dati.get("note_committente")
        if dati.get("note_committente")
        else "Nessuna istruzione particolare specificata. Attenersi al protocollo di trasporto standard."
    )
    pdf.multi_cell(184, 3.2, pulisci(istruzioni_extra), border=0, align="L")

    # ---------------------------------------------------------
    # FIRME DI CONVALIDA E RICEVUTA (Y: 238 -> 282)
    # ---------------------------------------------------------
    h_firme = 38
    y_firme = 238

    # Box Firma Mittente
    pdf.rect(10, y_firme, 60, h_firme)
    pdf.set_xy(12, y_firme + 2)
    pdf.set_font("Helvetica", "B", 7)
    pdf.cell(56, 3, pulisci("Firma Mittente / Caricatore"), align="C", ln=1)
    pdf.set_xy(12, y_firme + 32)
    pdf.set_font("Helvetica", "", 6)
    pdf.cell(56, 3, "Data e Ora: ____/____/________  ___:___", align="C")

    # Box Firma Vettore
    pdf.rect(75, y_firme, 60, h_firme)
    pdf.set_xy(77, y_firme + 2)
    pdf.set_font("Helvetica", "B", 7)
    pdf.cell(56, 3, pulisci("Firma Vettore / Conducente"), align="C", ln=1)
    pdf.set_xy(77, y_firme + 32)
    pdf.set_font("Helvetica", "", 6)
    pdf.cell(56, 3, "Per presa in carico della merce", align="C")

    # Box Firma Destinatario
    pdf.rect(140, y_firme, 60, h_firme)
    pdf.set_xy(142, y_firme + 2)
    pdf.set_font("Helvetica", "B", 7)
    pdf.cell(
        56,
        3,
        pulisci("Firma Destinatario (Ricevuta)"),
        align="C",
        ln=1,
    )
    pdf.set_xy(142, y_firme + 32)
    pdf.set_font("Helvetica", "", 6)
    pdf.cell(56, 3, "Data e Ora: ____/____/________  ___:___", align="C")

    # Output in byte per lo scarico tramite Streamlit
    out = pdf.output(dest="S")
    return (
        bytes(out)
        if isinstance(out, (bytes, bytearray))
        else out.encode("latin-1")
    )


def crea_pdf_preventivo(dati):
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.text(10, 20, "PREVENTIVO DI TRASPORTO")

    pdf.set_font("Helvetica", "", 10)
    pdf.text(10, 30, f"Data: {datetime.now().strftime('%d/%m/%Y')}")
    pdf.text(10, 40, f"Cliente: {pulisci(dati['cliente'])}")

    tipo_v = "Andata e Ritorno" if dati["is_ritorno"] else "Solo Andata"
    pdf.text(
        10,
        50,
        f"Tratta: {pulisci(dati['partenza'])} - {pulisci(dati['arrivo'])} ({tipo_v})",
    )

    pdf.line(10, 60, 200, 60)

    pdf.text(10, 70, "DETTAGLIO COSTI:")
    pdf.text(10, 80, f"Distanza totale calcolata: {dati['km']} Km")
    pdf.text(10, 87, f"Tariffa applicata: {dati['tariffa']} EUR / Km")
    pdf.text(10, 94, f"Costo Viaggio: {dati['costo_viaggio']:.2f} EUR")
    pdf.text(
        10, 101, f"Pedaggi Autostradali Stimati: {dati['pedaggio']:.2f} EUR"
    )

    pdf.line(10, 110, 200, 110)

    pdf.set_font("Helvetica", "B", 12)
    pdf.text(120, 125, f"Imponibile: {dati['imponibile']:.2f} EUR")
    pdf.text(120, 135, f"IVA (22%): {dati['iva']:.2f} EUR")
    pdf.set_font("Helvetica", "B", 14)
    pdf.text(120, 150, f"TOTALE: {dati['totale']:.2f} EUR")

    out = pdf.output(dest="S")
    return (
        bytes(out)
        if isinstance(out, (bytes, bytearray))
        else out.encode("latin-1")
    )


# ==========================================
# 4. INTERFACCIA GRAFICA (Streamlit)
# ==========================================
st.set_page_config(page_title="Gestionale Trasporti", layout="wide")
st.title("🚛 Gestionale Trasporti - Pannello di Controllo")

tab1, tab2, tab3 = st.tabs(
    ["📄 Bolle di Trasporto", "💰 Preventivi Intelligenti", "🕒 Cronologia"]
)

# ---------- TAB 1: BOLLE ----------
with tab1:
    st.subheader("Crea nuova Lettera di Vettura (CMR)")
    with st.form("form_bolla"):
        c1, c2, c3 = st.columns(3)
        num_doc = c1.text_input("Numero Documento", "2026-001")
        data_b = c2.text_input("Data", datetime.now().strftime("%d/%m/%Y"))
        ora_b = c3.text_input("Ora", "08:00")

        c4, c5 = st.columns(2)
        vettore = c4.text_input("Nome Tua Azienda (Vettore)", "Apostol Trasporti")
        committente = c5.text_input("Committente / Cliente", "Azienda Cliente Srl")

        ritiro = st.text_input(
            "Term. Ritiro / Carico", "LA SPEZIA CONTAINER TRML"
        )
        scarico = st.text_input("Luogo Scarico", "Magazzino Milano")

        c6, c7, c8 = st.columns(3)
        autista = c6.text_input("Autista", "Mario Rossi")
        trattore = c7.text_input("Targa Trattore", "AA123BB")
        rimorchio = c8.text_input("Targa Rimorchio", "XA762KF")

        c9, c10 = st.columns(2)
        container = c9.text_input("Numero Container", "ONEU 123456")
        peso = c10.text_input("Peso Merce (Kg)", "24000")

        note = st.text_area("Note e Osservazioni di Viaggio", "Sigillo N. 987654. Nessuna anomalia riscontrata.")
        note_committente = st.text_input("Istruzioni Speciali Committente", "Mantenere temperatura controllata / Consegna entro le ore 14:00")

        invia_bolla = st.form_submit_button("Genera Bolla PDF", type="primary")

    if invia_bolla:
        dati_b = {
            "num_doc": num_doc,
            "data": data_b,
            "ora": ora_b,
            "rif": "Rif. Ordine #9982",
            "compagnia": "MSC / ONE",
            "booking": "BK-908123",
            "committente": committente,
            "ritiro": ritiro,
            "scarico": scarico,
            "merce": "MERCE VARIA SU PALLET",
            "vettore": vettore,
            "autista": autista,
            "trattore": trattore,
            "rimorchio": rimorchio,
            "container": container,
            "peso": peso,
            "note": note,
            "note_committente": note_committente,
        }
        pdf_bytes = crea_pdf_bolla(dati_b)
        salva_cronologia(
            "Bolla Creata", committente, f"Viaggio verso {scarico}"
        )
        st.success("✅ Lettera di vettura (CMR) generata con successo!")
        st.download_button(
            "📥 Scarica Bolla PDF",
            data=pdf_bytes,
            file_name=f"Bolla_{num_doc}.pdf",
            mime="application/pdf",
        )

# ---------- TAB 2: PREVENTIVI ----------
with tab2:
    st.subheader("Calcola Preventivo e Percorso (Auto-Calcolo API)")
    cliente_prev = st.text_input("Nome Cliente", "Azienda Esempio S.p.A.")

    col_p1, col_p2 = st.columns(2)
    partenza = col_p1.text_input("Città di Partenza", "La Spezia")
    arrivo = col_p2.text_input("Città di Arrivo", "Roma")

    tipo_viaggio = st.radio(
        "Tipologia Viaggio:",
        ["Solo Andata", "Andata e Ritorno"],
        horizontal=True,
    )

    tariffa = st.number_input("Tariffa al Km (€)", value=1.50, step=0.10)

    if st.button("📍 Calcola Percorso e Costi", type="primary"):
        with st.spinner(
            "Connessione ai satelliti di geolocalizzazione in corso..."
        ):
            km, pedaggio = calcola_distanza_api(partenza, arrivo)

            if km:
                is_ritorno = tipo_viaggio == "Andata e Ritorno"
                if is_ritorno:
                    km = km * 2
                    pedaggio = pedaggio * 2

                costo_viaggio = km * tariffa
                imponibile = costo_viaggio + pedaggio
                iva = imponibile * 0.22
                totale = imponibile + iva

                st.success("✅ Calcolo completato con successo!")
                m1, m2, m3 = st.columns(3)
                m1.metric("Distanza Totale", f"{km} Km")
                m2.metric("Pedaggio Stimato", f"{pedaggio} €")
                m3.metric("Totale (IVA inc.)", f"{totale:.2f} €")

                dati_prev = {
                    "cliente": cliente_prev,
                    "partenza": partenza,
                    "arrivo": arrivo,
                    "is_ritorno": is_ritorno,
                    "km": km,
                    "tariffa": tariffa,
                    "costo_viaggio": costo_viaggio,
                    "pedaggio": pedaggio,
                    "imponibile": imponibile,
                    "iva": iva,
                    "totale": totale,
                }

                pdf_prev = crea_pdf_preventivo(dati_prev)
                dettaglio_cronologia = f"Tratta: {partenza} - {arrivo} ({'A/R' if is_ritorno else 'Andata'})"
                salva_cronologia(
                    "Preventivo Creato",
                    cliente_prev,
                    dettaglio_cronologia,
                    f"€ {totale:.2f}",
                )
                st.download_button(
                    "📥 Scarica Preventivo PDF",
                    data=pdf_prev,
                    file_name=f"Preventivo_{cliente_prev}.pdf",
                    mime="application/pdf",
                )
            else:
                st.error(
                    "⚠️ Non sono riuscito a trovare queste città. Controlla di averle scritte bene."
                )

# ---------- TAB 3: CRONOLOGIA ----------
with tab3:
    st.subheader("Storico dei documenti generati")
    if st.button("🔄 Aggiorna lista"):
        st.rerun()

    storico = carica_cronologia()
    if storico:
        st.dataframe(storico, use_container_width=True)
    else:
        st.info("Nessun documento creato finora. La cronologia è vuota.")