import pandas as pd
import streamlit as st
from io import BytesIO
import re
import unicodedata
import time

st.set_page_config(page_title="Sklad Checker", page_icon="📦", layout="wide")

st.title("📦 Sklad Checker")
st.write("""
Tato appka porovná tvůj export s exportem dodavatele, aktualizuje `stock` a `productVisibility`,
a zobrazí produkty, které již **nejsou u dodavatele** (včetně jejich variant *Namixuj si dárkový box*).
""")

# --- Pomocná funkce na očištění názvů ---
def normalize_name(name: str) -> str:
    name = str(name).lower().strip()
    name = re.sub(r"\(.*k(ó|o)d[:\s]*[^\)]*\)", "", name)
    name = re.sub(r"k(ó|o)d[:\s]*[0-9a-zA-Z\\-_/]*", "", name)
    name = re.sub(r"obj\.*[:\s]*[0-9a-zA-Z\\-_/]*", "", name)
    name = re.sub(r"\s*k(ó|o)d\s*[0-9a-zA-Z\\-_/]+", "", name)
    name = ''.join(c for c in unicodedata.normalize('NFD', name) if unicodedata.category(c) != 'Mn')
    name = re.sub(r"\s+", " ", name)
    return name.strip()

# --- Pomocná funkce pro bezpečné přečtení objemu ---
def get_objem_value(row, col_name):
    val = row.get(col_name, "")
    val_str = str(val).strip()
    m = re.search(r"[1-4]", val_str)
    return m.group(0) if m else "4"

# --- Nastavení pravidel ---
st.sidebar.header("⚙️ Nastavení pravidel")
min_stock_hide = st.sidebar.number_input("Skryj produkt, pokud má sklad ≤", min_value=0, max_value=100, value=2, step=1)

st.sidebar.markdown("---")
st.sidebar.subheader("📦 Limity pro Namixuj box podle objemu (variant:Objem)")
thresholds = {
    "1": st.sidebar.number_input("Velké (1)", min_value=0, max_value=100, value=2, step=1),
    "2": st.sidebar.number_input("Středně velké (2)", min_value=0, max_value=100, value=3, step=1),
    "3": st.sidebar.number_input("Střední (3)", min_value=0, max_value=100, value=5, step=1),
    "4": st.sidebar.number_input("Drobné (4)", min_value=0, max_value=100, value=9, step=1),
}

# --- Nahrání souborů ---
st.header("📂 Nahrání exportů")
muj_file = st.file_uploader("Nahraj **můj export (.xlsx)**", type=["xlsx"])
dod_file = st.file_uploader("Nahraj **export dodavatele (.xlsx)**", type=["xlsx"])

if muj_file and dod_file:
    st.success("✅ Soubory nahrány, můžeš pokračovat níže.")
    
    button_placeholder = st.empty()
    start = button_placeholder.button("🚀 Zpracovat")

    if start:
        button_placeholder.button("⏳ Načítám...", disabled=True)
        with st.spinner("Probíhá zpracování..."):
            time.sleep(0.5)

            muj = pd.read_excel(muj_file)
            dodavatel = pd.read_excel(dod_file)

            # --- Očištění ---
            for col in ["code", "name", "defaultCategory", "productVisibility"]:
                if col in muj.columns:
                    muj[col] = muj[col].astype(str).str.strip()
            for col in ["code", "name"]:
                dodavatel[col] = dodavatel[col].astype(str).str.strip()

            muj["stock"] = pd.to_numeric(muj.get("stock", 0), errors="coerce").fillna(0).astype(int)
            dodavatel["stock"] = pd.to_numeric(dodavatel.get("stock", 0), errors="coerce").fillna(0).astype(int)

            muj["_oldVisibility"] = muj["productVisibility"].astype(str).str.lower()

            # --- Najdi sloupec objemu ---
            objem_col = None
            for col in muj.columns:
                if "variant" in col.lower() and "objem" in col.lower():
                    objem_col = col
                    break

            dodavatel_stock_by_code = dict(zip(dodavatel["code"], dodavatel["stock"]))
            dodavatel_by_name_norm = {normalize_name(n): s for n, s in zip(dodavatel["name"], dodavatel["stock"])}

            pocet_zmen_stock = pocet_zmen_hidden = pocet_zmen_visible = 0
            chybejici_produkty = []
            chybejici_bez_namixuj = []
            ignore_codes = {"86827", "3625", "6202", "6199", "6205"}
            nove_skryte_produkty = []
            nove_viditelne_produkty = []

            # --- Hlavní logika ---
            for idx, row in muj.iterrows():
                code = str(row.get("code", "")).strip()
                name = str(row.get("name", "")).strip()
                name_norm = normalize_name(name)
                aktualni_stock = int(row.get("stock", 0))
                kategorie = str(row.get("defaultCategory", "")).lower().strip()
                old_viz = str(row.get("_oldVisibility", "")).lower()

                if code in ignore_codes:
                    continue

                # Určení nového skladu
                if code in dodavatel_stock_by_code:
                    novy_stock = dodavatel_stock_by_code[code]
                else:
                    novy_stock = dodavatel_by_name_norm.get(name_norm, None)

                if novy_stock is not None:
                    if aktualni_stock != novy_stock:
                        muj.at[idx, "stock"] = novy_stock
                        pocet_zmen_stock += 1

                    # --- Aktualizace Namixuj variant ---
                    stejny_nazev = row.get("name", "")
                    maska_namixuj = (
                        (muj["name"] == stejny_nazev) &
                        (muj["defaultCategory"].str.lower().str.strip() == "namixuj si dárkový box")
                    )

                    if maska_namixuj.any():
                        for idx_namixuj in muj[maska_namixuj].index:
                            velikost_nmj = get_objem_value(muj.loc[idx_namixuj], objem_col)
                            limit = thresholds.get(velikost_nmj, 9)

                            try:
                                stock_val = int(novy_stock)
                            except (TypeError, ValueError):
                                stock_val = int(muj.loc[idx_namixuj].get("stock", 0))

                            stare_viz = muj.loc[idx_namixuj, "_oldVisibility"]
                            nove_viz = "hidden" if stock_val <= limit else "visible"

                            if stare_viz != nove_viz:
                                muj.at[idx_namixuj, "productVisibility"] = nove_viz
                                if nove_viz == "hidden":
                                    pocet_zmen_hidden += 1
                                    nove_skryte_produkty.append(muj.loc[idx_namixuj].copy())
                                else:
                                    pocet_zmen_visible += 1
                                    nove_viditelne_produkty.append(muj.loc[idx_namixuj].copy())

                    # --- Aktualizace hlavního produktu ---
                    is_namixuj = "namixuj si dárkový box" in kategorie

                    if not is_namixuj:
                        nova_visibility = "hidden" if novy_stock <= min_stock_hide else "visible"
                        if old_viz != nova_visibility:
                            muj.at[idx, "productVisibility"] = nova_visibility
                            if nova_visibility == "hidden":
                                pocet_zmen_hidden += 1
                                nove_skryte_produkty.append(muj.loc[idx].copy())
                            else:
                                pocet_zmen_visible += 1
                                nove_viditelne_produkty.append(muj.loc[idx].copy())

                else:
                    if "namixuj si dárkový box" in kategorie:
                        stejny_nazev = muj[
                            (muj["name"].str.strip() == name) &
                            (muj["defaultCategory"].str.lower().str.strip() != "namixuj si dárkový box")
                        ]
                        if not stejny_nazev.empty:
                            continue

                    muj.at[idx, "productVisibility"] = "hidden"
                    chybejici_produkty.append(row)
                    chybejici_bez_namixuj.append(row)

            # --- Odstranit pomocný sloupec ---
            if "_oldVisibility" in muj.columns:
                muj = muj.drop(columns=["_oldVisibility"])
            muj.reset_index(drop=True, inplace=True)

            # --- Výstupy ---
            nove_viditelne = muj[
                (muj["productVisibility"].astype(str).str.lower() == "visible") &
                (~muj["code"].isin(ignore_codes))
            ]
            nove_viditelne_namixuj = nove_viditelne[
                nove_viditelne["defaultCategory"].str.lower().str.contains("namixuj")
            ]
            nove_viditelne_bez_namixuj = nove_viditelne[
                ~nove_viditelne["defaultCategory"].str.lower().str.contains("namixuj")
            ]

            st.success("✅ Zpracování dokončeno!")
            st.write(f"📊 Změněných skladů: {pocet_zmen_stock}")
            st.write(f"🔻 Skrytých produktů: {pocet_zmen_hidden}")
            st.write(f"👁️ Zviditelněných produktů: {pocet_zmen_visible}")
            st.write(f"❌ Chybějících produktů (bez Namixuj): {len(chybejici_bez_namixuj)}")
            st.write(f"✅ Viditelných po úpravě celkem: **{len(nove_viditelne)}**")
            st.write(f" • mimo Namixuj: {len(nove_viditelne_bez_namixuj)}")
            st.write(f" • v Namixuj: {len(nove_viditelne_namixuj)}")

            st.markdown("---")
            if chybejici_produkty:
                st.subheader("❌ Produkty, které již nejsou u dodavatele (včetně Namixuj variant)")
                neexistujici_df = pd.DataFrame(chybejici_produkty).drop_duplicates(subset=["code"])
                st.dataframe(neexistujici_df[["code", "name", "defaultCategory", "stock", "productVisibility"]],
                            use_container_width=True)
            else:
                st.info("✅ Žádné produkty nechybí u dodavatele.")

            if nove_skryte_produkty:
                st.markdown("---")
                st.subheader(f"🫥 Produkty, které se nově skryly ({len(nove_skryte_produkty)})")
                nove_skryte_df = pd.DataFrame(nove_skryte_produkty).drop_duplicates(subset=["code"])
                st.dataframe(
                    nove_skryte_df[["code", "name", "defaultCategory", "stock", "productVisibility"]],
                    use_container_width=True
                )
            else:
                st.info("✅ Žádné nové produkty se neskrývaly.")

            if nove_viditelne_produkty:
                st.markdown("---")
                st.subheader(f"👁️ Produkty, které se nově odkryly ({len(nove_viditelne_produkty)})")
                nove_viditelne_df = pd.DataFrame(nove_viditelne_produkty).drop_duplicates(subset=["code"])
                st.dataframe(
                    nove_viditelne_df[["code", "name", "defaultCategory", "stock", "productVisibility"]],
                    use_container_width=True
                )
            else:
                st.info("✅ Žádné nové produkty se neodkryly.")

            unmatched = muj[
                (~muj["code"].astype(str).isin(dodavatel["code"].astype(str))) &
                (muj["defaultCategory"].str.lower().str.strip() != "namixuj si dárkový box") &
                (~muj["code"].astype(str).isin(ignore_codes))
            ]
            if not unmatched.empty:
                st.markdown("---")
                st.subheader(f"⚠️ Produkty, které se nepodařilo spárovat podle 'code' ({len(unmatched)})")
                st.dataframe(
                    unmatched[["code", "name", "defaultCategory", "stock", "productVisibility"]],
                    use_container_width=True
                )
            else:
                st.info("✅ Všechny produkty se podařilo spárovat podle 'code'.")

            duplicates = muj[muj["code"].astype(str).duplicated(keep=False)]
            duplicates = duplicates[~duplicates["code"].isin(ignore_codes)]

            if not duplicates.empty:
                st.markdown("---")
                st.subheader(f"⚠️ Nalezeny duplicitní kódy v mém exportu ({len(duplicates)})")
                st.write("Níže jsou produkty, které mají stejný 'code':")
                st.dataframe(
                    duplicates[["code", "name", "defaultCategory", "stock", "productVisibility"]],
                    use_container_width=True
                )
            else:
                st.info("✅ Žádné duplicitní kódy nebyly nalezeny.")

            # --- Uložení výsledku ---
            output = BytesIO()
            muj.to_excel(output, index=False)
            output.seek(0)
            st.download_button(
                label="⬇️ Stáhnout výsledek (vystup.xlsx)",
                data=output,
                file_name="vystup.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
