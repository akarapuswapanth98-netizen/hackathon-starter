"""Offline-first RAG templates - local vector store, document ingestion, and retrieval with citations.

This module provides reusable RAG capabilities that work entirely offline:
- Local vector store using ChromaDB or FAISS
- Document ingestion and chunking
- Retrieval with source citations
- Offline embedding model support
"""


class BaseDocument:
    """Base document class for RAG pipelines."""

    def __init__(self, page_content: str, metadata: dict = None):
        self.page_content = page_content
        self.metadata = metadata or {}


class RecursiveCharacterTextSplitter:
    """Recursive character text splitter for document chunking."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200, separators: list = None):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", " ", ""]

    def split_text(self, text: str) -> list:
        """Split text into chunks.

        Args:
            text: Text to split

        Returns:
            List of text chunks
        """
        if len(text) <= self.chunk_size:
            return [text]

        # Try splitting by separators
        chunks = []
        separator = self.separators[0]

        # Simple recursive splitting
        remaining = text
        while remaining:
            # Find the best split point
            best_split = -1
            for sep in self.separators:
                idx = remaining.find(sep)
                if idx != -1 and (best_split == -1 or idx < best_split):
                    best_split = idx
                    separator = sep

            if best_split == -1:
                # No separator found, take chunk_size chars
                chunks.append(remaining[:self.chunk_size])
                remaining = remaining[self.chunk_size:]
            else:
                # Split at the separator
                chunk = remaining[:best_split + len(separator)]
                chunks.append(chunk)
                remaining = remaining[best_split + len(separator):]

        # Merge chunks that are too small
        merged = []
        current = ""
        for chunk in chunks:
            if len(current) + len(chunk) <= self.chunk_size:
                current += chunk + "\n"
            else:
                if current.strip():
                    merged.append(current.strip())
                current = chunk + "\n"

        if current.strip():
            merged.append(current.strip())

        return merged

    def split_documents(self, documents: list) -> list:
        """Split a list of documents into chunks.

        Args:
            documents: List of BaseDocument objects

        Returns:
            List of chunked BaseDocument objects
        """
        chunks = []
        for doc in documents:
            text_chunks = self.split_text(doc.page_content)
            for i, chunk in enumerate(text_chunks):
                chunk_meta = dict(doc.metadata)
                chunk_meta["chunk_index"] = i
                chunk_meta["total_chunks"] = len(text_chunks)
                chunks.append(BaseDocument(page_content=chunk, metadata=chunk_meta))
        return chunks


class ChromaDBStore:
    """Local vector store using ChromaDB for offline RAG."""

    def __init__(self, persist_directory: str = "./data/chroma", embedding_model: str = "all-MiniLM-L6-v2"):
        self.persist_directory = persist_directory
        self.embedding_model_name = embedding_model
        self.client = None
        self.collection = None
        self._initialized = False

    def initialize(self):
        """Initialize ChromaDB client and collection."""
        try:
            import chromadb

            self.client = chromadb.PersistentClient(path=self.persist_directory)

            # Check if collection exists, create if not
            try:
                self.collection = self.client.get_collection(name="rag_docs")
                print("Found existing ChromaDB collection")
            except Exception:
                self.collection = self.client.create_collection(name="rag_docs")
                print("Created new ChromaDB collection")

            self._initialized = True
        except ImportError:
            print("chromadb not installed; install with: pip install chromadb")
            self._initialized = False
        except Exception as e:
            print(f"Failed to initialize ChromaDB: {e}")
            self._initialized = False

    def add_documents(self, documents: list, ids: list = None):
        """Add documents to the vector store.

        Args:
            documents: List of BaseDocument objects
            ids: Optional list of document IDs (generated if not provided)
        """
        if not self._initialized:
            self.initialize()

        if not self._initialized or self.collection is None:
            return

        try:
            # Prepare data for ChromaDB
            documents_data = []
            metadatas = []
            ids_list = []

            for i, doc in enumerate(documents):
                doc_id = ids[i] if ids and i < len(ids) else f"doc_{i}_{id(doc)}"
                # Simple text embedding - in production, use the embedding model
                documents_data.append(doc.page_content)
                metadatas.append(doc.metadata)
                ids_list.append(doc_id)

            self.collection.add(
                documents=documents_data,
                metadatas=metadatas,
                ids=ids_list,
            )
            print(f"Added {len(documents)} documents to ChromaDB")
        except Exception as e:
            print(f"Failed to add documents to ChromaDB: {e}")

    def similarity_search(self, query: str, k: int = 4) -> list:
        """Search for similar documents.

        Args:
            query: Search query
            k: Number of results to return

        Returns:
            List of (document, similarity_score) tuples
        """
        if not self._initialized or self.collection is None:
            return []

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=k,
            )

            # Format results
            docs = []
            if results["documents"] and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                    score = results["distances"][0][i] if results["distances"] else 1.0
                    docs.append((BaseDocument(page_content=doc, metadata=metadata), score))

            return docs
        except Exception as e:
            print(f"Similarity search failed: {e}")
            return []

    def get(self, ids: list = None) -> dict:
        """Get documents by IDs.

        Args:
            ids: List of document IDs

        Returns:
            Dictionary with documents and metadatas
        """
        if not self._initialized or self.collection is None:
            return {"documents": [], "metadatas": []}

        try:
            results = self.collection.get(ids=ids or [])
            return {
                "documents": results.get("documents", []),
                "metadatas": results.get("metadatas", []),
            }
        except Exception as e:
            print(f"Get documents failed: {e}")
            return {"documents": [], "metadatas": []}


class FAISSStore:
    """Local vector store using FAISS for offline RAG.

    FAISS (Facebook AI Similarity Search) is efficient for large-scale
    vector similarity search.
    """

    def __init__(self, dimension: int = 384, index_path: str = None):
        self.dimension = dimension
        self.index_path = index_path
        self.index = None
        self.documents = []  # List of (document, metadata) tuples
        self._initialized = False

    def initialize(self):
        """Initialize FAISS index."""
        try:
            import faiss

            self.index = faiss.IndexFlatL2(self.dimension)
            self._initialized = True
            print("FAISS index initialized")
        except ImportError:
            print("faiss not installed; install with: pip install faiss-cpu")
            self._initialized = False
        except Exception as e:
            print(f"Failed to initialize FAISS: {e}")
            self._initialized = False

    def add_documents(self, embeddings: list, documents: list, metadatas: list = None):
        """Add document embeddings to the FAISS index.

        Args:
            embeddings: List of embedding vectors (list of floats)
            documents: List of document strings
            metadatas: Optional list of metadata dicts
        """
        if not self._initialized:
            self.initialize()

        if not self._initialized or self.index is None:
            return

        try:
            # Convert embeddings to FAISS format
            import numpy as np

            embeddings_array = np.array(embeddings, dtype=np.float32)

            # Add to index
            self.index.add(embeddings_array)

            # Store documents and metadata
            for i, doc in enumerate(documents):
                meta = metadatas[i] if metadatas and i < len(metadatas) else {}
                self.documents.append((doc, meta))

            print(f"Added {len(documents)} documents to FAISS index")
        except Exception as e:
            print(f"Failed to add documents to FAISS: {e}")

    def similarity_search(self, embedding: list, k: int = 4) -> list:
        """Search for similar documents using query embedding.

        Args:
            embedding: Query embedding vector
            k: Number of results to return

        Returns:
            List of (document, metadata, distance) tuples
        """
        if not self._initialized or self.index is None:
            return []

        try:
            import numpy as np

            # Reshape embedding for FAISS
            query_array = np.array(embedding, dtype=np.float32).reshape(1, -1)

            # Search
            distances, indices = self.index.search(query_array, min(k, len(self.documents)))

            results = []
            for i, (dist, idx) in enumerate(zip(distances[0], indices[0])):
                if idx < len(self.documents):
                    doc, meta = self.documents[idx]
                    results.append((doc, meta, dist))

            return results
        except Exception as e:
            print(f"FAISS similarity search failed: {e}")
            return []


class RagPipeline:
    """Offline-first RAG pipeline - document ingestion to retrieval."""

    def __init__(self, store_type: str = "chromadb", embedder: str = "all-MiniLM-L6-v2"):
        self.store_type = store_type
        self.embedder_name = embedder
        self.store = None
        self.text_splitter = RecursiveCharacterTextSplitter()
        self._initialized = False

    def initialize(self):
        """Initialize the RAG pipeline based on store type."""
        if self.store_type == "chromadb":
            self.store = ChromaDBStore(
                persist_directory="./data/chroma",
                embedding_model=self.embedder_name,
            )
        elif self.store_type == "faiss":
            self.store = FAISSStore(dimension=384)

        self.store.initialize()
        self._initialized = True
        print(f"RAG pipeline initialized with {self.store_type}")

    def ingest_documents(self, file_paths: list, chunk_size: int = 1000, chunk_overlap: int = 200):
        """Ingest documents from file paths.

        Args:
            file_paths: List of file paths to ingest
            chunk_size: Size of text chunks
            chunk_overlap: Overlap between chunks
        """
        if not self._initialized:
            self.initialize()

        from langchain.text_splitter import RecursiveCharacterTextSplitter as LCTextSplitter
        from langchain.document_loaders import TextLoader, PyPDFLoader, UnstructuredHTMLLoader

        all_documents = []

        for filepath in file_paths:
            try:
                # Determine file type and load accordingly
                if filepath.endswith(".pdf"):
                    loader = PyPDFLoader(filepath)
                elif filepath.endswith(".html") or filepath.endswith(".htm"):
                    loader = UnstructuredHTMLLoader(filepath)
                else:
                    loader = TextLoader(filepath, encoding="utf8")

                docs = loader.load()
                all_documents.extend(docs)
                print(f"Loaded {len(docs)} documents from {filepath}")
            except Exception as e:
                print(f"Failed to load {filepath}: {e}")

        # Split documents into chunks
        chunks = self.text_splitter.split_documents(all_documents)
        print(f"Split {len(all_documents)} documents into {len(chunks)} chunks")

        # Add to store
        if self.store:
            # Extract just the page content and metadata
            doc_objects = []
            for chunk in chunks:
                doc_objects.append(
                    type("Doc", (), {"page_content": chunk.page_content, "metadata": chunk.metadata})()
                )

            doc_ids = [f"chunk_{i}" for i in range(len(doc_objects))]
            self.store.add_documents(doc_objects, ids=doc_ids)

    def retrieve(self, query: str, k: int = 4) -> list:
        """Retrieve relevant documents for a shows me as "assistant" and the user asking me to resume and speed up work.

2. The last assistant action was editing the requirements.txt and running tests, which passed (51 tests).

3. The user wants me to continue with the v2 specification upgrade, specifically:
- Phase 2: ML templates (already in progress - I created ml/templates.py and updated requirements.txt)
- Phase 3: Computer Vision templates (already started - I created vision/templates.py)
- Phase 5: MapsProvider abstraction
- Phase 6: Optional JWT auth
- Phase 7: Explainability & audit logging
- Phase 8: LIVE/DEMO/AUTO modes

Let me verify what's been done and what needs to be done.Now let me continue with Phase 5 - MapsProvider abstraction with haversine fallback. Let me first check what's already there:
<tool_call>
<function=shell>
<parameter=workdir>
C:\Users\akara\hackathon-starter\backend