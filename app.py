import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage

from src.imdb_anwar.workflow import workflow


st.set_page_config(page_title="IMDb Movie Assistant", page_icon="🎬")
st.title("IMDb Movie Assistant")
st.caption("Jawaban diambil dari Qdrant dan detail data SQLite.")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "movies" not in st.session_state:
    st.session_state.movies = []
if "analysis" not in st.session_state:
    st.session_state.analysis = []
if "usage" not in st.session_state:
    st.session_state.usage = {}

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if st.button("Reset chat"):
    st.session_state.messages = []
    st.session_state.movies = []
    st.session_state.analysis = []
    st.session_state.usage = {}
    st.rerun()

question = st.chat_input("Tanyakan tentang film IMDb...")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    history = [
        HumanMessage(content=item["content"])
        if item["role"] == "user"
        else AIMessage(content=item["content"])
        for item in st.session_state.messages[:-1]
    ]
    result = workflow.invoke({"question": question, "chat_history": history})
    answer = result["answer"]
    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.session_state.movies = result.get("movies", [])
    st.session_state.analysis = result.get("analysis", [])
    st.session_state.usage = result.get("usage", {})

    with st.chat_message("assistant"):
        st.markdown(answer)

with st.sidebar:
    st.header("RAG sources")
    for movie in st.session_state.movies:
        st.markdown(
            f"**{movie['Series_Title']}**  \n"
            f"Score: {movie['similarity_score']} | IMDb: {movie['IMDB_Rating']}"
        )
    for row in st.session_state.analysis:
        st.markdown(
            f"**{row['Series_Title']}**  \n"
            f"Gross: {row['Gross_cleaned']} | IMDb: {row['IMDB_Rating']}"
        )
    if not st.session_state.movies and not st.session_state.analysis:
        st.info("Sumber film tampil setelah pertanyaan dikirim.")

    st.header("LLM usage")
    usage = st.session_state.usage
    st.metric("Total tokens", usage.get("total_tokens", 0))
    st.caption(
        f"Input: {usage.get('input_tokens', 0)} | "
        f"Output: {usage.get('output_tokens', 0)}"
    )
