 Phase 14b - Evolution Test Coverage

  CONTEXTE :
  La Roadmap V7.7 (P0) impose de sécuriser le module core/evolution/ avant toute nouvelle fonctionnalité.
  Ce module est le moteur d'auto-amélioration de NEXUS, mais il manque de tests unitaires (< 20% coverage).

  MISSION :
  Créer une suite de tests unitaires complète pour les composants critiques de l'évolution.

  SPÉCIFICATIONS TECHNIQUES :

   1. `tests/test_evolution_core.py` :
       * Test `EvolutionManager` :
           * Mocker GeminiDriver et ClaudeDriver pour simuler des réponses d'IA (ne pas consommer de tokens).
           * Tester le cycle complet : run_evolution_cycle -> start_cycle -> brainstorm -> evaluate -> apply.
           * Vérifier que le cycle s'arrête correctement si brainstorm échoue (pas de boucle infinie).
       * Test `Evaluator` :
           * Vérifier le calcul de fitness (score composite).
           * Vérifier la détection des régressions (score actuel < score précédent).

   2. `tests/test_mutation_parser.py` :
       * Test `MutationParser` :
           * Tester l'extraction de blocs JSON valides (avec et sans balises Markdown).
           * Tester la résilience face aux erreurs courantes (JSON malformé, champs manquants).
           * Tester la validation stricte des chemins (interdiction de modifier hors de core/ ou workspace/).

  LIVRABLES :
   1. tests/test_evolution_core.py.
   2. tests/test_mutation_parser.py.
   3. Exécution réussie (pytest sur ces fichiers).

  GO.