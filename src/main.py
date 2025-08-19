import streamlit as st
import os
import requests
import time
# from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

st.title("Chatbot with RAG + Gemma-3 (FAISS + Local Embeddings)")

# Initialize FAISS vector store từ local với embedding mạnh hơn và chuẩn hóa
try:
    embeddings = HuggingFaceEmbeddings(
        model_name="./src/models/local_e5_large_v2",
        encode_kwargs={"normalize_embeddings": True}
    )
    vector_store = FAISS.load_local("./src/FAISS_Vector", embeddings, allow_dangerous_deserialization=True)
except Exception as e:
    st.error(f"Lỗi khởi tạo FAISS hoặc embeddings: {str(e)}")
    st.stop()

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.messages.append(SystemMessage("You are an assistant for question-answering tasks."))

# Display chat history
for message in st.session_state.messages:
    if isinstance(message, HumanMessage):
        with st.chat_message("user"):
            st.markdown(message.content)
    elif isinstance(message, AIMessage):
        with st.chat_message("assistant"):
            st.markdown(message.content)

# Input chat
prompt = st.chat_input("Nhập câu hỏi của bạn:")

# Nếu có prompt từ người dùng
if prompt:
    full_start_time = time.time()

    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append(HumanMessage(prompt))

    try:
        # Giai đoạn 1: Embedding
        embed_start = time.time()
        query_vector = embeddings.embed_query(prompt)
        embed_time = time.time() - embed_start

        # Giai đoạn 2: Tìm kiếm FAISS
        search_start = time.time()
        docs = vector_store.similarity_search_by_vector(query_vector, k=3)
        search_time = time.time() - search_start

        docs_text = "\n".join(d.page_content for d in docs)

    except Exception as e:
        st.error(f"Lỗi khi tìm context từ FAISS: {str(e)}")
        docs_text = ""

    if not docs_text:
        st.warning("Không có dữ liệu context được tìm thấy.")

    # Tạo system prompt từ context
    system_prompt = f"""Bạn là trợ lý AI thông minh của Công ty Tiximax Logistic. 
                    Bạn chuyên hỗ trợ cung cấp các thông tin của công ty dựa theo các tài liệu đã đưa vào. 
                    Bạn sẽ hỗ trợ cho các phòng ban như quản lý, sale, tiếp thị và nhân sự. 
                    Trả lời bằng các từ ngữ dễ nghe, phù hợp với chuyên ngành. Nếu bạn không có thông tin trả lời, cứ nói tôi không biết. \nContext: {docs_text}"""

    st.session_state.messages.append(SystemMessage(system_prompt))

    # Chuẩn bị messages để gửi tới LLM Local API
    message_list = [
        {"role": "system", "content": system_prompt}
    ] + [
        {"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": m.content}
        for m in st.session_state.messages if not isinstance(m, SystemMessage)
    ]

    # Giai đoạn 3: Gọi LLM
    try:
        llm_start = time.time()
        response = requests.post(
            "http://192.168.2.8:1234/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": "gemma-3n-e4b-it-text",
                "messages": message_list,
                "temperature": 0.5,
                "max_tokens": 512
            }
        )
        response.raise_for_status()
        result = response.json()["choices"][0]["message"]["content"]
        llm_time = time.time() - llm_start

        full_elapsed_time = time.time() - full_start_time

        with st.chat_message("assistant"):
            st.markdown(result)
            st.caption(f"Tổng thời gian: {full_elapsed_time:.2f} giây | Embedding: {embed_time:.2f}s | Tìm kiếm: {search_time:.2f}s | LLM: {llm_time:.2f}s")

        st.session_state.messages.append(AIMessage(result))

    except Exception as e:
        st.error(f"Lỗi khi gọi LLM local API: {str(e)}")
    