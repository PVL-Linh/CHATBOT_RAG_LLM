try:
    from .Prosessing_HR.Embedding_FAISS_HR import main_HR
    from .Embedding_FAISS import main_All
except:
    from Prosessing_HR.Embedding_FAISS_HR import main_HR
    from Embedding_FAISS import main_All


if __name__ == "__main__":
    # main_All()
    main_HR()