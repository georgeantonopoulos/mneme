# Person and Entity Retrieval

Use this workflow when the user asks “What do you know about X?” or names a person, company, or project.

## Retrieval sequence

1. **Start exact and narrow.** Run Mneme retrieval using the canonical name and known aliases first. Avoid padding the initial prompt with generic terms such as `person`, `company`, `context`, `projects`, `relationship`, or `recent`; those common tokens can dominate cluster scoring and bury the named entity.
2. **Run semantic activation separately.** Use `mneme think` as an associative second pass, not as proof. Generic `email_message` activations are leads that must be resolved back to source IDs.
3. **Judge the result before answering.** A technically non-empty result is still a retrieval failure if the named entity is absent or unrelated clusters dominate. Say so internally and continue searching.
4. **Follow source provenance.** For email-backed entities, inspect the surfaced `email_message:<id>` records in Gmail. Search both exact name and address variants, read the newest messages in each thread, and use full MIME bodies rather than snippets for factual claims.
5. **Separate evidence layers.** Distinguish:
   - public biography from authoritative/public sources;
   - the user’s private relationship and recent activity from Gmail/calendar/vault;
   - judgment or strategic interpretation, clearly labelled as such.
6. **Consolidate only verified facts.** If no clean `People/<name>.md` exists, create one through `mneme note write` after source verification. Include aliases, relationship, current themes, dated interactions, and source links. Never infer contact details.
7. **Refresh the neural index after the write** so the new person neuron can surface directly next time.

## Quality bar

A good person answer should cover:

- who they are;
- how the user knows them;
- what has happened recently;
- active projects or commitments;
- why the relationship may matter;
- source confidence and any open uncertainty.

Do not dump every email. Synthesize the relationship from concrete interactions. Do not claim that Mneme “knows” the person when it only returned generic email nodes or unrelated clusters.

## Failure pattern to avoid

A broad query such as `X: who is X, relationship, company, projects, conversations, commitments, contact details, recent context` can score generic “projects/context” clusters above X. The fix is not more prompt words. Retry with the exact entity name and aliases, then follow direct source IDs and source-of-truth searches.