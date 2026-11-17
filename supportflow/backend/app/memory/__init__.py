"""Agent memory.

* Episodic (``episodic.py``): what happened, per customer and in time order. Stored in PostgreSQL next to the
  tickets it describes, recalled by customer so the classifier sees "this customer chased the same refund twice".
* Semantic (``semantic.py``): what the team knows, independent of when it was learned. Resolved tickets and agent
  corrections live in a ChromaDB vector store and are recalled by meaning, not by customer.

Resolving a ticket consolidates an episode into semantic memory: its resolution becomes knowledge any later
ticket can retrieve. Overriding the AI's classification stores a correction the classifier is shown the next
time a near-identical ticket arrives.
"""
