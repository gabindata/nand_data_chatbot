import streamlit as st
import polars as pl
import duckdb
import os
import requests
import re

# =====================================
# SQL 寃利??ㅼ젙
# =====================================

# =====================================
# SQL 寃利??ㅼ젙
# =====================================

ALLOWED_TABLE = "nand_health"

ALLOWED_COLUMNS = {#而щ읆 ?뺤젙 ???섏젙
    "unit_id",
    "model",
    "pe_cycle",
    "temperature_c",
    "error_count",
    "unstable_count",
    "capacity_gb",
    "usage_hours"
}

def validate_sql(sql: str):

    if not sql or not sql.strip():
        return False, "SQL???앹꽦?섏? ?딆븯?듬땲??"

    sql = sql.strip()
    sql_upper = sql.upper()

    # 1. ?щ윭 SQL 臾몄옣 ?ㅽ뻾 諛⑹?
    if ";" in sql.rstrip(";"):
        return False, "?щ윭 SQL 臾몄옣? ?ㅽ뻾?????놁뒿?덈떎."

    # 2. SELECT留??덉슜
    if not re.match(r"^\s*SELECT\b", sql_upper):
        return False, "SELECT 臾몃쭔 ?ъ슜?????덉뒿?덈떎."

    # 3. ?꾪뿕??SQL 紐낅졊 李⑤떒
    forbidden_keywords = [
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER",
        "CREATE", "TRUNCATE", "ATTACH", "DETACH",
        "COPY", "EXPORT", "IMPORT"
    ]

    for keyword in forbidden_keywords:
        if re.search(rf"\b{keyword}\b", sql_upper):
            return False, f"{keyword} 紐낅졊? ?ъ슜?????놁뒿?덈떎."

    # =====================================
    # [?섏젙] 臾몄옄??由ы꽣???쒓굅??"寃???꾩슜" SQL ?앹꽦
    # 而щ읆/?뚯씠釉??좏겙 寃?щ뒗 ??踰꾩쟾?쇰줈留??섑뻾?섍퀬,
    # ?ㅼ젣 ?ㅽ뻾(con.execute)?먮뒗 ?먮낯 sql??洹몃?濡??ъ슜?쒕떎.
    # =====================================
    # 'It''s ok' 泥섎읆 ?댁뒪耳?댄봽???묒??곗샂??') ???ы븿?댁꽌 ?덉쟾?섍쾶 ?쒓굅
    sql_for_check = re.sub(r"'(?:[^']|'')*'", "''", sql)

    # 4. ?뚯씠釉?寃??(寃?ъ슜 SQL 湲곗?)
    table_pattern = r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    tables = re.findall(table_pattern, sql_for_check, re.IGNORECASE)

    for table in tables:
        if table.lower() != ALLOWED_TABLE:
            return False, f"?덉슜?섏? ?딆? ?뚯씠釉붿엯?덈떎: {table}"

    # 5. 而щ읆 寃??(寃?ъ슜 SQL 湲곗? ??由ы꽣???대? 媛믪? ?ш린 ??嫄몃┝)
    column_pattern = r"\b[a-zA-Z_][a-zA-Z0-9_]*\b"
    tokens = re.findall(column_pattern, sql_for_check)

    alias_pattern = r"\bAS\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    aliases = set(
        alias.upper()
        for alias in re.findall(alias_pattern, sql_for_check, re.IGNORECASE)
    )

    sql_keywords = {
        "SELECT", "FROM", "WHERE", "GROUP", "BY", "ORDER", "ASC", "DESC",
        "LIMIT", "OFFSET", "AS", "AND", "OR", "NOT", "IN", "IS", "NULL",
        "BETWEEN", "LIKE", "CASE", "WHEN", "THEN", "ELSE", "END",
        "COUNT", "AVG", "SUM", "MAX", "MIN", "DISTINCT", "HAVING",
        "OVER", "PARTITION", "ROW_NUMBER", "RANK", "DENSE_RANK",
        "TRUE", "FALSE", "MESSAGE"
    }

    sql_functions = {
        "COUNT", "AVG", "SUM", "MAX", "MIN",
        "ROUND", "COALESCE", "CAST", "NULLIF"
    }

    for token in tokens:
        token_upper = token.upper()

        if token_upper in aliases:
            continue
        if token_upper in sql_keywords:
            continue
        if token_upper in sql_functions:
            continue
        if token.lower() == ALLOWED_TABLE:
            continue
        if token_upper in {"INTEGER", "BIGINT", "DOUBLE", "VARCHAR", "DECIMAL"}:
            continue

        if token.lower() not in ALLOWED_COLUMNS:
            if token_upper not in {"NAND_HEALTH"}:
                return False, f"?덉슜?섏? ?딆? 而щ읆 ?먮뒗 ?앸퀎?먯엯?덈떎: {token}"

    return True, ""

from openai import OpenAI

# =====================================
# 泥?겕 ?낅줈???⑥닔
# =====================================

def upload_file_in_chunks(
    file_path,
    upload_server_url="http://127.0.0.1:8000"
):

    file_size = os.path.getsize(file_path)

    filename = os.path.basename(file_path)


    # 1. ?낅줈??珥덇린??    init_response = requests.post(
        f"{upload_server_url}/upload/init",

        data={
            "filename": filename,
            "file_size": file_size
        }
    )


    init_response.raise_for_status()


    upload_info = init_response.json()


    upload_id = upload_info["upload_id"]

    chunk_size = upload_info["chunk_size"]

    total_chunks = upload_info["total_chunks"]


    progress_bar = st.progress(0)

    status_text = st.empty()


    # 2. 泥?겕 ?⑥쐞 ?낅줈??    with open(file_path, "rb") as file:

        for chunk_index in range(total_chunks):

            chunk_data = file.read(chunk_size)


            response = requests.post(

                f"{upload_server_url}/upload/chunk",

                data={
                    "upload_id": upload_id,
                    "chunk_index": chunk_index
                },

                files={
                    "chunk": (
                        f"chunk_{chunk_index}",
                        chunk_data
                    )
                }
            )


            response.raise_for_status()


            progress = (
                chunk_index + 1
            ) / total_chunks


            progress_bar.progress(progress)


            status_text.text(
                f"?낅줈??以?.. "
                f"{chunk_index + 1}/{total_chunks} "
                f"泥?겕 ?꾨즺"
            )


    # 3. ?낅줈???꾨즺
    complete_response = requests.post(

        f"{upload_server_url}/upload/complete",

        data={
            "upload_id": upload_id,
            "filename": filename,
            "total_chunks": total_chunks
        }
    )


    complete_response.raise_for_status()


    result = complete_response.json()


    progress_bar.progress(1.0)


    status_text.success(
        "??⑸웾 ?뚯씪 ?낅줈???꾨즺!"
    )


    return result["file_path"]
st.set_page_config(
    page_title="NAND Health Chatbot",
    page_icon="?뮶"
)

st.title("?뮶 NAND Health Data Chatbot")


# =====================================
# ?곗씠???낅젰 諛⑹떇 ?좏깮
# =====================================

data_mode = st.radio(
    "?곗씠???낅젰 諛⑹떇???좏깮?섏꽭??,
    [
        "?뱚 ?뚯씪 ?낅줈??,
        "?? ??⑸웾 Parquet ?뚯씪 ?ъ슜"
    ]
)


# =====================================
# DuckDB ?곌껐
# =====================================

@st.cache_resource
def get_duckdb_connection():

    return duckdb.connect()
con = get_duckdb_connection()




# =====================================
# 1. ?쇰컲 ?뚯씪 ?낅줈??# =====================================

if data_mode == "?뱚 ?뚯씪 ?낅줈??:

    uploaded_file = st.file_uploader(
        "?뱚 NAND Health csv ?뚯씪???낅줈?쒗븯?몄슂",
        type=["csv"]
    )

    if uploaded_file is not None:

        with st.spinner("?뚯씪???쎈뒗 以?.."):

            file_name = uploaded_file.name

            # CSV
            if file_name.endswith(".csv"):

                data = pl.read_csv(uploaded_file)

            
            # DuckDB???깅줉
            con.register("uploaded_data", data)

            con.execute("""
                CREATE OR REPLACE VIEW nand_health AS
                SELECT *
                FROM uploaded_data
            """)

        st.success("?곗씠???낅줈???꾨즺!")
        st.write(f"珥?{data.height:,}媛쒖쓽 ?곗씠?곌? ?덉뒿?덈떎.")

        with st.expander("?뱤 ?곗씠??誘몃━蹂닿린"):

            preview = con.execute(
                "SELECT * FROM nand_health LIMIT 100"
            ).pl()

            st.dataframe(preview)

# =====================================
# 2. ??⑸웾 ?뚯씪 釉뚮씪?곗? ?낅줈??# =====================================

else:

    st.subheader(
        "?? ??⑸웾 ?뚯씪 泥?겕 ?낅줈??
    )

    # HTML ?뚯씪 ?쎄린
    with open(
        "large_upload.html",
        "r",
        encoding="utf-8"
    ) as file:

        html_code = file.read()


    # Streamlit ?붾㈃??HTML ?낅줈???쒖떆
    st.components.v1.html(
        html_code,
        height=500,
        scrolling=True
    )


    st.divider()


    st.subheader(
        "?뱛 ?낅줈?쒕맂 ?뚯씪 ?곌껐"
    )


    if st.button(
        "?봽 理쒓렐 ?낅줈???뚯씪 媛?몄삤湲?
    ):

        try:

            response = requests.get(
                "http://127.0.0.1:8000/upload/latest"
            )


            response.raise_for_status()


            upload_info = response.json()


            final_file_path = upload_info[
                "file_path"
            ]


            st.success(
                "理쒓렐 ?낅줈???뚯씪??李얠븯?듬땲??"
            )


            st.write(
                f"?뚯씪紐? {upload_info['filename']}"
            )


            st.write(
                f"?뚯씪 寃쎈줈: {final_file_path}"
            )


            # =====================================
            # Parquet ?곗씠???곌껐
            # =====================================

            con.execute(
                f"""
                CREATE OR REPLACE VIEW nand_health AS
                SELECT *
                FROM read_parquet(
                    '{final_file_path}'
                )
                """
            )


            st.success(
                "???먮룞 ?앹꽦??Parquet瑜?DuckDB???곌껐?덉뒿?덈떎!"
            )


            count_result = con.execute(
                "SELECT COUNT(*) FROM nand_health"
            ).fetchone()[0]


            st.write(
                f"珥?{count_result:,}媛쒖쓽 ?곗씠?곌? ?덉뒿?덈떎."
            )


            with st.expander(
                "?뱤 ?곗씠??誘몃━蹂닿린"
            ):

                preview = con.execute(
                    "SELECT * FROM nand_health LIMIT 100"
                ).pl()


                st.dataframe(
                    preview
                )


        except Exception as e:

            st.error(
                "?뚯씪 ?곌껐 以??ㅻ쪟媛 諛쒖깮?덉뒿?덈떎."
            )


            st.code(
                str(e)
            )


# =====================================
# API ???뺤씤
# =====================================
# =====================================
# API ???뺤씤
# =====================================

api_key = os.environ.get("OPENAI_API_KEY")

if not api_key:

    st.error("OPENAI_API_KEY媛 ?ㅼ젙?섏? ?딆븯?듬땲??")

    st.stop()


client = OpenAI(api_key=api_key)


# =====================================
# ?덉떆)而щ읆 ?뺤젙 ???섏젙
# =====================================

schema = """
?뚯씠釉붾챸: nand_health

而щ읆 ?뺤쓽:

- unit_id
  ?섎?: NAND ?좊떅 ?앸퀎??  ?ъ슜???쒗쁽: ?좊떅, NAND, ?μ튂, ?쒗뭹 踰덊샇

- pe_cycle
  ?섎?: PE Cycle ?잛닔
  ?ъ슜???쒗쁽: PE Cycle, PE ?ъ씠?? PE, ?곌린 ?잛닔

- unstable_count
  ?섎?: NAND??遺덉븞??諛쒖깮 ?잛닔
  ?ъ슜???쒗쁽: 遺덉븞???잛닔, 遺덉븞??諛쒖깮, unstable

- model
  ?섎?: NAND 紐⑤뜽紐?  ?ъ슜???쒗쁽: 紐⑤뜽, ?쒗뭹 紐⑤뜽

- capacity_gb
  ?섎?: NAND ?⑸웾(GB)
  ?ъ슜???쒗쁽: ?⑸웾, ????⑸웾, GB

- temperature_c
  ?섎?: NAND ?⑤룄(??뵪)
  ?ъ슜???쒗쁽: ?⑤룄, 諛쒖뿴, ??뵪, ?④굅???뺣룄

- error_count
  ?섎?: NAND?먯꽌 諛쒖깮???ㅻ쪟 ?잛닔
  ?ъ슜???쒗쁽: ?ㅻ쪟, ?먮윭, ?ㅻ쪟 ?잛닔, ?먮윭 ?잛닔

- usage_hours
  ?섎?: NAND ?ъ슜 ?쒓컙
  ?ъ슜???쒗쁽: ?ъ슜 ?쒓컙, ?ъ슜 湲곌컙
"""



# =====================================
# 吏덈Ц ?낅젰
# =====================================

question = st.chat_input(
    "?? PE Cycle??300 ?댁긽???좊떅? 紐?媛쒖빞?"
)


# =====================================
# 理쒓렐 ?낅줈??Parquet ?먮룞 ?곌껐
# =====================================

if os.path.exists(
    "upload_info.json"
):

    import json


    with open(
        "upload_info.json",
        "r",
        encoding="utf-8"
    ) as info_file:

        upload_info = json.load(
            info_file
        )


    final_file_path = upload_info[
        "file_path"
    ]


    if os.path.exists(
        final_file_path
    ):

        con.execute(
            f"""
            CREATE OR REPLACE VIEW nand_health AS
            SELECT *
            FROM read_parquet(
                '{final_file_path}'
            )
            """
        )
if question:

    st.chat_message("user").write(question)

    # =====================================
    # AI SQL ?앹꽦 #而щ읆 ?뺤젙???섏젙
    # =====================================

    with st.spinner("AI媛 SQL???앹꽦?섎뒗 以?.."):

        prompt = f"""
?덈뒗 NAND Health ?곗씠??遺꾩꽍??SQL ?앹꽦湲곕떎.

{schema}

?ъ슜??吏덈Ц:
{question}

==================================================
1. ??븷
==================================================

?덉쓽 ??븷? ?ъ슜?먯쓽 ?먯뿰??吏덈Ц??DuckDB?먯꽌 ?ㅽ뻾 媛?ν븳 ???섎굹??SELECT SQL 臾몄쑝濡?蹂?섑븯??寃껋씠??

諛섎뱶???ㅼ젣 ?곗씠???뚯씠釉?nand_health???ㅼ젣 而щ읆留??ъ슜?쒕떎.

SQL???앹꽦????
- 吏덈Ц???녿뒗 議곌굔??異붽??섏? ?딅뒗??
- 而щ읆 ?섎?瑜??꾩쓽濡?異붿륫?섏? ?딅뒗??
- schema???녿뒗 而щ읆??留뚮뱾?대궡吏 ?딅뒗??
- SQL???ㅻ챸臾몄쓣 ?ы븿?섏? ?딅뒗??
- 理쒖쥌 異쒕젰? SQL 臾??섎굹留?異쒕젰?쒕떎.

==================================================
2. ?ㅼ젣 ?뚯씠釉?==================================================

?뚯씠釉붾챸:
nand_health

?ъ슜 媛?ν븳 ?ㅼ젣 而щ읆:

unit_id
model
pe_cycle
temperature_c
error_count
unstable_count
capacity_gb
usage_hours

==================================================
3. 而щ읆 ?섎? 留ㅽ븨 洹쒖튃
==================================================

?ъ슜?먯쓽 ?쒗쁽???꾨옒 紐⑸줉???ы븿?섎㈃
諛섎뱶???대떦 而щ읆???ъ슜?쒕떎.

[?ㅻ쪟 愿??
"?ㅻ쪟"
"?먮윭"
"?ㅻ쪟 ?섏튂"
"?먮윭 ?섏튂"
"?ㅻ쪟 媛쒖닔"
"?먮윭 媛쒖닔"
"?ㅻ쪟 ?잛닔"
"?먮윭 ?잛닔"
??error_count

[遺덉븞??愿??
"遺덉븞??
"遺덉븞???잛닔"
"遺덉븞??諛쒖깮"
"unstable"
??unstable_count

[?⑤룄 愿??
"?⑤룄"
"諛쒖뿴"
"?④굅???뺣룄"
"??뵪 ?⑤룄"
"??뵪"
??temperature_c

[PE Cycle 愿??
"PE"
"PE Cycle"
"PE ?ъ씠??
"?곌린 ?잛닔"
??pe_cycle

[?ъ슜 ?쒓컙 愿??
"?ъ슜 ?쒓컙"
"?ъ슜 湲곌컙"
??usage_hours

[?⑸웾 愿??
"?⑸웾"
"????⑸웾"
"GB"
??capacity_gb

[紐⑤뜽 愿??
"紐⑤뜽"
"?쒗뭹 紐⑤뜽"
??model

[?좊떅 愿??
"?좊떅"
"NAND"
"?μ튂"
"?쒗뭹 踰덊샇"
??unit_id

==================================================
4. ?덈? ?쇰룞?섎㈃ ???섎뒗 而щ읆
==================================================

?ㅻ쪟? 遺덉븞?뺤? ?쒕줈 ?ㅻⅨ 媛쒕뀗?대떎.

"?ㅻ쪟", "?먮윭"
??error_count

"遺덉븞??, "unstable"
??unstable_count

?덈? ?ㅼ쓬怨?媛숈씠 ?댁꽍?섏? ?딅뒗??

?ㅻ쪟 ??unstable_count ??遺덉븞????error_count ??
?⑤룄? ?ㅻ쪟???쒕줈 ?ㅻⅨ 媛쒕뀗?대떎.

?⑤룄 ??temperature_c
?ㅻ쪟 ??error_count

?ъ슜 ?쒓컙怨?PE Cycle???쒕줈 ?ㅻⅨ 媛쒕뀗?대떎.

?ъ슜 ?쒓컙 ??usage_hours
PE Cycle ??pe_cycle

==================================================
5. 吏덈Ц??紐낆떆??議곌굔留??ъ슜
==================================================

?ъ슜?먭? 吏덈Ц?먯꽌 ?멸툒?섏? ?딆? 議곌굔???꾩쓽濡?異붽??섏? ?딅뒗??

?덈? ?ㅼ뼱:

?ъ슜??
"?⑤룄媛 70?꾨낫???믪? NAND??紐?媛쒖빞?"

?щ컮瑜?SQL:
SELECT COUNT(*)
FROM nand_health
WHERE temperature_c > 70;

?섎せ??SQL:
SELECT COUNT(*)
FROM nand_health
WHERE temperature_c > 70
AND error_count > 10;

?ㅻ쪟 議곌굔? ?ъ슜?먭? 留먰븯吏 ?딆븯?쇰?濡?異붽??섎㈃ ???쒕떎.

==================================================
6. 紐⑦샇???곹깭쨌怨좎옣쨌?덉쭏 ?쒗쁽 泥섎━ 洹쒖튃
==================================================

?ㅼ쓬 ?쒗쁽? ?뱀젙 而щ읆?대굹 議곌굔?쇰줈 ?꾩쓽 ?댁꽍?섏? ?딅뒗??

[怨좎옣 諛?怨좎옣 ?꾪뿕]
- 怨좎옣??寃?媛숈? NAND
- 怨좎옣 ?꾪뿕???믪? NAND
- 怨좎옣 ?꾪뿕 NAND
- 怨좎옣 媛?μ꽦???믪? NAND
- 怨좎옣??NAND
- 怨?怨좎옣??NAND
- 臾몄젣媛 諛쒖깮??NAND

[臾몄젣 諛??댁긽 ?곹깭]
- 臾몄젣媛 ?덈뒗 NAND
- 臾몄젣媛 留롮? NAND
- ?댁긽???덈뒗 NAND
- ?댁긽 NAND
- 遺덈웾 NAND
- 遺덈웾??留롮? NAND
- ?꾪뿕??NAND

[?곹깭 諛??덉쭏]
- 嫄닿컯??NAND
- ?곹깭媛 醫뗭? NAND
- ?곹깭媛 ??醫뗭? NAND
- ?덉쭏??醫뗭? NAND
- ?덉쭏???섏걶 NAND
- ?깅뒫??醫뗭? NAND
- ?깅뒫???섏걶 NAND

[?섎챸 諛??명썑??
- ?섎챸???쇰쭏 ?⑥? ?딆? NAND
- ?ㅻ옒??NAND
- ?명썑??NAND

==================================================
紐⑦샇??吏덈Ц 泥섎━ ?먯튃
==================================================

?꾩? 媛숈? ?쒗쁽留??덇퀬 援ъ껜?곸씤 ?섏튂 湲곗??대굹
紐낆떆?곸씤 而щ읆 議곌굔???녿뒗 寃쎌슦:

1. temperature_c瑜??꾩쓽濡??좏깮?섏? ?딅뒗??
2. error_count瑜??꾩쓽濡??좏깮?섏? ?딅뒗??
3. unstable_count瑜??꾩쓽濡??좏깮?섏? ?딅뒗??
4. pe_cycle???꾩쓽濡??좏깮?섏? ?딅뒗??
5. usage_hours瑜??꾩쓽濡??좏깮?섏? ?딅뒗??
6. ?щ윭 而щ읆???꾩쓽濡?議고빀?섏? ?딅뒗??
7. error_count > 0 議곌굔???꾩쓽濡?異붽??섏? ?딅뒗??
8. unstable_count > 0 議곌굔???꾩쓽濡?異붽??섏? ?딅뒗??
9. temperature_c > ?뱀젙 媛?議곌굔???꾩쓽濡?異붽??섏? ?딅뒗??
10. pe_cycle > ?뱀젙 媛?議곌굔???꾩쓽濡?異붽??섏? ?딅뒗??
11. usage_hours > ?뱀젙 媛?議곌굔???꾩쓽濡?異붽??섏? ?딅뒗??

援ъ껜?곸씤 湲곗????녿뒗 紐⑦샇??吏덈Ц?
諛섎뱶???ㅼ쓬 SQL??異쒕젰?쒕떎.

SELECT '吏덈Ц??湲곗???紐낇솗?섏? ?딆뒿?덈떎.' AS message;

==================================================
援ъ껜?곸씤 湲곗????덈뒗 寃쎌슦
==================================================

吏덈Ц??紐낆떆??援ъ껜?곸씤 湲곗????덉쑝硫?洹?湲곗?留??ъ슜?쒕떎.

?덉떆 1:

?ъ슜??吏덈Ц:
"怨좎옣??寃?媛숈? NAND??紐?媛쒖빞?"

??湲곗? ?놁쓬
??諛섎뱶??

SELECT '吏덈Ц??湲곗???紐낇솗?섏? ?딆뒿?덈떎.' AS message;

?덉떆 2:

?ъ슜??吏덈Ц:
"?ㅻ쪟媛 10媛??댁긽?닿퀬 遺덉븞???잛닔媛 5???댁긽??怨좎옣 ?꾪뿕 NAND??紐?媛쒖빞?"

??紐낆떆??議곌굔留??ъ슜:

error_count >= 10
AND unstable_count >= 5

?덉긽 SQL:

SELECT COUNT(*)
FROM nand_health
WHERE error_count >= 10
AND unstable_count >= 5;

?덉떆 3:

?ъ슜??吏덈Ц:
"?⑤룄媛 70???댁긽??NAND瑜?怨좎옣 ?꾪뿕?쇰줈 蹂닿퀬
紐?媛쒖빞?"

???ъ슜?먭? ?⑤룄 湲곗???吏곸젒 ?쒖떆?덉쑝誘濡?

SELECT COUNT(*)
FROM nand_health
WHERE temperature_c >= 70;

?덉떆 4:

?ъ슜??吏덈Ц:
"PE Cycle??1000 ?댁긽???ㅻ옒??NAND??紐?媛쒖빞?"

??PE Cycle 湲곗?留??ъ슜:

SELECT COUNT(*)
FROM nand_health
WHERE pe_cycle >= 1000;

?덉떆 5:

?ъ슜??吏덈Ц:
"?ъ슜 ?쒓컙??10000?쒓컙 ?댁긽??NAND??紐?媛쒖빞?"

???ъ슜 ?쒓컙 湲곗?留??ъ슜:

SELECT COUNT(*)
FROM nand_health
WHERE usage_hours >= 10000;

==================================================
紐⑦샇???쒗쁽怨?援ъ껜??議곌굔???곗꽑?쒖쐞
==================================================

"怨좎옣", "?꾪뿕", "遺덈웾", "?곹깭媛 ??醫뗫떎",
"嫄닿컯?섏? ?딅떎"? 媛숈? ?쒗쁽?
洹??먯껜濡?SQL 議곌굔???꾨땲??

諛섎뱶??吏덈Ц??紐낆떆??援ъ껜?곸씤 ?섏튂 議곌굔留??ъ슜?쒕떎.

??

"怨좎옣??寃?媛숈? NAND 以묒뿉???⑤룄媛 70???댁긽??寃껋? 紐?媛쒖빞?"

??"怨좎옣??寃?媛숇떎"??紐⑦샇???쒗쁽?대?濡?臾댁떆?쒕떎.
??紐낆떆???⑤룄 議곌굔留??ъ슜?쒕떎.

SELECT COUNT(*)
FROM nand_health
WHERE temperature_c >= 70;

??

"臾몄젣媛 ?덈뒗 NAND 以??ㅻ쪟媛 10媛??댁긽??寃껋? 紐?媛쒖빞?"

??"臾몄젣媛 ?덈뒗 NAND"??紐⑦샇???쒗쁽?대?濡?臾댁떆?쒕떎.
??紐낆떆???ㅻ쪟 議곌굔留??ъ슜?쒕떎.

SELECT COUNT(*)
FROM nand_health
WHERE error_count >= 10;

??

"嫄닿컯??NAND 以??ъ슜 ?쒓컙??1000?쒓컙 ?댄븯??寃껋? 紐?媛쒖빞?"

??"嫄닿컯??NAND"??紐⑦샇???쒗쁽?대?濡?臾댁떆?쒕떎.
??紐낆떆???ъ슜 ?쒓컙 議곌굔留??ъ슜?쒕떎.

SELECT COUNT(*)
FROM nand_health
WHERE usage_hours <= 1000;

==================================================
7. 吏묎퀎 洹쒖튃
==================================================

?ъ슜?먭? ?붽뎄??吏묎퀎 諛⑹떇留??ъ슜?쒕떎.

"紐?媛?
"媛쒖닔"
"紐?媛쒖쓽 NAND"
"紐?媛쒖쓽 ?좊떅"
??COUNT(*)

"?됯퇏"
??AVG()

"?⑷퀎"
??SUM()

"理쒕뙎媛?
"媛???믪? 媛?
??MAX()

"理쒖넖媛?
"媛????? 媛?
??MIN()

??

"?⑤룄???됯퇏"
??AVG(temperature_c)

"?ㅻ쪟 媛쒖닔???⑷퀎"
??SUM(error_count)

"媛???믪? PE Cycle"
??MAX(pe_cycle)

==================================================
8. NAND 媛쒖닔? ?ㅻ쪟 ?⑷퀎瑜?援щ텇
==================================================

?ъ슜?먭? NAND ?먮뒗 ?좊떅??媛쒖닔瑜?臾쇱쑝硫?COUNT(*)瑜??ъ슜?쒕떎.

??

"?⑤룄媛 70???댁긽??NAND??紐?媛쒖빞?"
??COUNT(*)

諛섎㈃:

"?ㅻ쪟??珥앺빀??"
??SUM(error_count)

"?ㅻ쪟媛 諛쒖깮??NAND??紐?媛쒖빞?"
??COUNT(*)
WHERE error_count > 0

==================================================
9. 洹몃９蹂?遺꾩꽍
==================================================

?ъ슜?먭? "紐⑤뜽蹂?, "紐⑤뜽留덈떎"?쇨퀬 ?섎㈃
GROUP BY model???ъ슜?쒕떎.

??

"紐⑤뜽蹂?NAND 媛쒖닔"
??SELECT model, COUNT(*) AS unit_count
FROM nand_health
GROUP BY model;

"紐⑤뜽蹂??됯퇏 ?⑤룄"
??SELECT model, AVG(temperature_c) AS avg_temperature
FROM nand_health
GROUP BY model;

==================================================
10. ?쒖쐞 ?쒗쁽
==================================================

"媛???믪?"
"理쒓퀬"
"?곸쐞"
"留롮? ??

??ORDER BY ?대떦媛?DESC

"媛?????"
"理쒖?"
"?섏쐞"
"?곸? ??

??ORDER BY ?대떦媛?ASC

??

"紐⑤뜽蹂??ㅻ쪟媛 媛??留롮? ?쒖꽌"
??GROUP BY model
ORDER BY error_count DESC

==================================================
11. 議곌굔 ?쒗쁽
==================================================

"?댁긽"
??>=

"珥덇낵"
"蹂대떎 ?믪쓬"
??>

"?댄븯"
??<=

"誘몃쭔"
"蹂대떎 ??쓬"
??<

"媛숈쓬"
??=

"?꾨땶"
??!=

"洹몃━怨?
??AND

"?먮뒗"
??OR

??

"?⑤룄媛 70???댁긽?닿퀬 ?ㅻ쪟媛 10媛?珥덇낵"
??temperature_c >= 70
AND error_count > 10

==================================================
12. SQL ?묒꽦 洹쒖튃
==================================================

1. 諛섎뱶??SELECT濡??쒖옉?쒕떎.
2. ?뚯씠釉붾챸? 諛섎뱶??nand_health瑜??ъ슜?쒕떎.
3. FROM nand_health瑜??ъ슜?쒕떎.
4. schema??議댁옱?섎뒗 而щ읆留??ъ슜?쒕떎.
5. SELECT, WHERE, GROUP BY, ORDER BY??紐⑤뱺 而щ읆? ?ㅼ젣 而щ읆?댁뼱???쒕떎.
6. DROP, DELETE, UPDATE, INSERT, ALTER, CREATE, TRUNCATE ?깆쓣 ?ъ슜?섏? ?딅뒗??
7. ?щ윭 SQL 臾몄옣??異쒕젰?섏? ?딅뒗??
8. SQL ?ㅻ챸臾몄쓣 異쒕젰?섏? ?딅뒗??
9. Markdown 肄붾뱶 釉붾줉???ъ슜?섏? ?딅뒗??
10. SQL ?섎굹留?異쒕젰?쒕떎.
11. ?ъ슜?먯쓽 吏덈Ц???녿뒗 議곌굔??異붽??섏? ?딅뒗??
12. ?ъ슜?먯쓽 ?쒗쁽??媛??癒쇱? 而щ읆 ?섎? 留ㅽ븨 洹쒖튃怨?鍮꾧탳?쒕떎.

==================================================
13. SQL ?앹꽦 ??理쒖쥌 ?먭?
==================================================

SQL??異쒕젰?섍린 ?꾩뿉 諛섎뱶???ㅼ쓬???뺤씤?쒕떎.

[而щ읆 ?먭?]
- 紐⑤뱺 而щ읆??schema??議댁옱?섎뒗媛?

[?섎? ?먭?]
- ?ㅻ쪟瑜?error_count濡?留ㅽ븨?덈뒗媛?
- 遺덉븞?뺤쓣 unstable_count濡?留ㅽ븨?덈뒗媛?
- ?⑤룄瑜?temperature_c濡?留ㅽ븨?덈뒗媛?
- PE Cycle??pe_cycle濡?留ㅽ븨?덈뒗媛?
- ?ъ슜 ?쒓컙??usage_hours濡?留ㅽ븨?덈뒗媛?

[議곌굔 ?먭?]
- ?ъ슜?먭? 留먰븯吏 ?딆? 議곌굔??異붽??섏? ?딆븯?붽??

[吏묎퀎 ?먭?]
- 媛쒖닔??COUNT(*)?멸??
- ?됯퇏? AVG()?멸??
- ?⑷퀎??SUM()?멸??
- 理쒕뙎媛믪? MAX()?멸??
- 理쒖넖媛믪? MIN()?멸??

[?뚯씠釉??먭?]
- nand_health留??ъ슜?덈뒗媛?

[?덉쟾 ?먭?]
- SELECT 臾??섎굹留?異쒕젰?섎뒗媛?

==================================================
14. 理쒖쥌 異쒕젰
==================================================

理쒖쥌 ?듬??먮뒗 SQL 肄붾뱶留?異쒕젰?쒕떎.

SQL:
"""

        response = client.chat.completions.create(
               model="gpt-4o-mini",
              messages=[
                 {
                      "role": "system",
                       "content": "?덈뒗 ?뺥솗??SQL???앹꽦?섎뒗 ?곗씠??遺꾩꽍 ?꾨Ц媛??"
                   },
                 {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0
        )
    
        sql = response.choices[0].message.content.strip()
    
        sql = sql.replace("```sql", "")
        sql = sql.replace("```", "")
        sql = sql.strip()
    
    
    # =====================================
    # ?앹꽦??SQL ?쒖떆
    # =====================================
    
    st.subheader("?쭬 AI媛 ?앹꽦??SQL")
    
    st.code(
        sql,
        language="sql"
    )
    
    
    # =====================================
    # SQL 寃利?諛??ㅽ뻾
    # =====================================
    
    try:
    
        is_valid, error_message = validate_sql(sql)
    
        if not is_valid:
    
            st.error(
                f"??SQL 寃利??ㅽ뙣: {error_message}"
            )
    
            st.stop()
    
    
        result = con.execute(sql).pl()
    
    
        # =====================================
        # 遺꾩꽍 寃곌낵
        # =====================================
    
        st.subheader("?뱤 遺꾩꽍 寃곌낵")
    
        st.dataframe(result)
    
    
        # =====================================
        # AI 寃곌낵 ?붿빟
        # =====================================
    
        result_text = str(result)
    
        summary_prompt = f"""
    ?덈뒗 NAND Health ?곗씠??遺꾩꽍 寃곌낵瑜??쎄쾶 ?ㅻ챸?섎뒗 遺꾩꽍 ?꾨Ц媛??
    
    ?ъ슜??吏덈Ц:
    {question}
    
    SQL ?ㅽ뻾 寃곌낵:
    {result_text}
    
    洹쒖튃:
    1. 寃곌낵瑜??쒓뎅?대줈 ?쒕몢 臾몄옣?쇰줈 ?붿빟?쒕떎.
    2. ?レ옄??媛?ν븳 ??泥??⑥쐞 ?쇳몴瑜??ъ슜?쒕떎.
    3. 寃곌낵???녿뒗 ?댁슜? 異붿륫?섏? ?딅뒗??
    4. 遺꾩꽍 寃곌낵留?媛꾧껐?섍쾶 ?ㅻ챸?쒕떎.
    5. 寃곌낵媛 "吏덈Ц??湲곗???紐낇솗?섏? ?딆뒿?덈떎."?쇰㈃
       湲곗???紐낇솗?섏? ?딆븘 遺꾩꽍?????녿떎怨??ㅻ챸?쒕떎.
    
    ?붿빟:
    """
    
    
        summary_response = client.chat.completions.create(
    
            model="gpt-4o-mini",
    
            messages=[
    
                {
                    "role": "user",
                    "content": summary_prompt
                }
    
            ],
    
            temperature=0
    
        )
    
    
        summary = (
            summary_response
            .choices[0]
            .message.content
            .strip()
        )
    
    
        st.subheader("?뮕 AI 遺꾩꽍 ?붿빟")
    
        st.info(summary)
    
    
        # =====================================
        # ?⑥씪 寃곌낵硫?Metric ?먮뒗 硫붿떆吏 ?쒖떆
        # =====================================
    
        if (
            result.shape[0] == 1
            and result.shape[1] == 1
        ):
    
            value = result.item(
                row=0,
                column=0
            )
    
    
            # ?レ옄??寃쎌슦
            if isinstance(value, (int, float)):
    
                st.metric(
    
                    label="遺꾩꽍 寃곌낵",
    
                    value=f"{value:,.0f}"
    
                )
    
    
            # 臾몄옄?댁씤 寃쎌슦
            else:
    
                st.info(
                    str(value)
                )
    
    
    except Exception as e:
    
        st.error(
            "SQL ?ㅽ뻾 以??ㅻ쪟媛 諛쒖깮?덉뒿?덈떎."
         )
    
        st.code(
            str(e)
        )
