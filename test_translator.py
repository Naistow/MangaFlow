from core.translator.llm_service import MangaLLMTranslator

def main():
    print("Отправка тестового запроса в Ollama...")
    translator = MangaLLMTranslator()
    
    test_phrases = [
        "What is that monster?!",
        "Guts, watch out behind you!",
        "I will never forgive Griffith."
    ]
    
    translated = translator.translate_bubbles_batch(test_phrases)
    
    print("\n--- Результат перевода ---")
    for orig, trans in zip(test_phrases, translated):
        print(f"[{orig}] -> [{trans}]")

if __name__ == "__main__":
    main()