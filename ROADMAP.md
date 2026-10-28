This roadmap details the development plan for NEXUS-Formatter, aiming to transition it from a proof-of-concept to a highly reliable, fast, and professional local utility.

### ⚙️ P0: Foundational Reliability (Blocks Real-World Use)
The priority is stabilizing the core AI interaction.
*   **Structured Output:** Replacing fragile marker-based parsing with strict JSON output via Ollama's format payload, significantly reducing parsing failures.
*   **Robustness:** Implementing response streaming to save partial notes when context limits (`num_ctx`) are hit, preventing entire batch failures.
*   **Control:** Making resource limits (`num_ctx`, `num_predict`) and service availability checks explicit and configurable.

### 🚀 P1: Performance and Coverage (High Impact)
Focus is on maximizing throughput and expanding input capability.
*   **Throughput:** Refactoring the batch processing loop to support parallel execution, utilizing hardware better.
*   **Input Resilience:** Adding OCR fallback capabilities to extract text from scanned PDFs.
*   **User Control:** Providing explicit flags for advanced workflow management (`--retry-failed`, `--resume`, `--since`) and enforcing configuration validation via schema.

### ✨ P2: Quality, Extensibility, and Integrity
This phase focuses on making the tool smarter, more modular, and safer.
*   **System Modularity:** Abstracting the AI provider layer (e.g., `OllamaClient`) to allow easy integration with OpenAI-compatible endpoints (LM Studio, vLLM).
*   **Data Integrity:** Implementing link validation against the existing vault structure and advanced deduplication using embedding comparisons.
*   **Operational Safety:** Ensuring atomic writes for output notes and implementing conflict detection to warn users before overwriting edited files.

### 🌟 P3: Polish and Workflow Enhancements
These are usability improvements for a better end-user experience.
*   Adding watch mode for live workflows.
*   Improving packaging for standard CLI installation.
*   Enhancing verbose logging and dry-run output.