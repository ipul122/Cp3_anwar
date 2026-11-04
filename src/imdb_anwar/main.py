from config import qdrant_client, COLLECTION_NAME, embeddings, llm, get_movie_by_id
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

def retrieve_context(query: str, top_k: int = 3) -> str:
    """Mengubah prompt menjadi vektor, cari ID di Qdrant, lalu ambil konteks dari SQLite."""
    # Step 1: Vektorisasi query
    query_vector = embeddings.embed_query(query)

    # Step 2: Similarity Search di Qdrant
    search_res = qdrant_client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k
    ).points

    # Step 3: Ambil metadata dari SQLite menggunakan ID hasil pencarian Qdrant
    contexts = []
    for hit in search_res:
        movie = get_movie_by_id(int(hit.id))
        if movie:
            contexts.append(f"- **{movie['title']}** (Score: {hit.score:.2f}): {movie['overview']}")
    
    return "\n".join(contexts)

# Setup Prompt Template & RAG Chain
system_prompt = """Kamu adalah asisten rekomendasi film IMDb yang ramah dan membantu.
Jawab pertanyaan pengguna secara informatif menggunakan referensi konteks film berikut:

--- KONTEKS FILM ---
{context}
--------------------
"""

prompt_template = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("user", "{question}")
])

rag_chain = prompt_template | llm | StrOutputParser()

def main():
    print("=" * 60)
    print("🎬 IMDb RAG Chatbot (Terminal Version)")
    print("Ketik 'exit' atau 'q' untuk keluar dari program.")
    print("=" * 60 + "\n")

    while True:
        try:
            user_input = input("\nUser: ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ["exit", "q", "quit"]:
                print("Terima kasih! Sampai jumpa.")
                break

            print("\n[...] Mencari rekomendasi film di Qdrant & SQLite...")
            context_text = retrieve_context(user_input, top_k=3)

            print("[...] Menggenerasi jawaban...")
            response = rag_chain.invoke({
                "context": context_text,
                "question": user_input
            })

            print("\n" + "=" * 20 + " Hasil Rekomendasi " + "=" * 20)
            print(response)
            print("-" * 59)

        except KeyboardInterrupt:
            print("\nProgram dihentikan.")
            break
        except Exception as e:
            print(f"\n[Error]: {e}")

if __name__ == "__main__":
    main()