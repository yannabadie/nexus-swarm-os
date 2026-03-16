"""
CLI Inspector - Détection dynamique des modèles disponibles

Ce module détecte automatiquement:
- Les CLIs installés (gemini, claude)
- Les modèles disponibles (Ultra, Pro, Flash, Opus, Sonnet, Haiku)
- Les context windows
- Les versions

Utilisé par bootstrap() pour vérifier l'environnement au démarrage.
"""

import platform
import subprocess


class CLIInspector:
    """Inspect installed CLI tools and detect models dynamically"""

    def _run_cli_command(self, command: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
        """
        Run CLI command with platform-specific handling.

        On Windows, some CLIs (like gemini, claude) need to be invoked via PowerShell.

        Args:
            command: Command as list (e.g., ["gemini", "--version"])
            timeout: Timeout in seconds

        Returns:
            CompletedProcess result
        """
        is_windows = platform.system() == "Windows"

        if is_windows and command[0] in ["gemini", "claude"]:
            # On Windows, gemini and claude need PowerShell
            cmd_str = " ".join(command)
            command = ["powershell", "-Command", cmd_str]

        return subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
        )

    def inspect_gemini(self) -> dict:
        """
        Detect Gemini CLI and model

        Tries to:
        1. Run `gemini --version` to check if CLI exists
        2. Run `gemini models list` to detect active model
        3. Parse output to identify model type (Ultra, Pro, Flash)

        Returns:
            {
                "available": bool,
                "model": str,           # e.g. "gemini-2.0-ultra"
                "context_window": int,  # tokens
                "version": str,         # CLI version
                "error": str            # if not available
            }
        """
        try:
            # Try gemini --version (using platform-aware helper)
            result = self._run_cli_command(["gemini", "--version"], timeout=10)

            if result.returncode != 0:
                return {"available": False, "error": "gemini CLI not found or not in PATH"}

            version = result.stdout.strip()

            # Try to detect model from gemini models list
            # Default to gemini-3.1-pro-preview (latest flagship preview on 2026-03-09)
            model = "gemini-3.1-pro-preview"
            context_window = 1000000  # Gemini 3 Pro: 1M token context window

            try:
                # Reduced timeout to prevent bootstrap bottleneck (was 20s)
                models_result = self._run_cli_command(["gemini", "models", "list"], timeout=10)

                output_lower = models_result.stdout.lower()

                # Parse output for active model (Gemini 3 -> 2.5 -> 2.0 -> 1.5)
                if "3-pro" in output_lower or "gemini 3" in output_lower:
                    model = "gemini-3.1-pro-preview"
                    context_window = 1000000  # Gemini 3 Pro: 1M token context window
                elif "2.5-pro" in output_lower or "gemini 2.5" in output_lower or "2.5 pro" in output_lower:
                    model = "gemini-2.5-pro"
                    context_window = 1000000  # Gemini 2.5 Pro: 1M token context window (March 2025)
                elif "ultra" in output_lower or "2.0-ultra" in output_lower:
                    model = "gemini-2.0-ultra"
                    context_window = 1000000
                elif "2.0-pro" in output_lower:
                    model = "gemini-2.0-pro"
                    context_window = 128000
                elif "flash" in output_lower or "2.0-flash" in output_lower or "2.5-flash" in output_lower:
                    model = "gemini-2.5-flash" if "2.5" in output_lower else "gemini-2.0-flash"
                    context_window = 32000
                elif "1.5-pro" in output_lower:
                    model = "gemini-1.5-pro"
                    context_window = 2000000

            except subprocess.TimeoutExpired:
                # Model detection timed out (PowerShell overhead on Windows)
                # Graceful fallback to latest model - not critical for bootstrap
                pass  # Silent fallback - model already set to default

            except Exception as e:
                # Other errors (network, CLI error, etc.)
                print(f"   Warning: Could not detect Gemini model: {e}")
                print(f"   Using default: {model}")

            return {"available": True, "model": model, "context_window": context_window, "version": version}

        except FileNotFoundError:
            return {"available": False, "error": "gemini command not found. Is Google AI CLI installed?"}

        except subprocess.TimeoutExpired:
            # gemini --version timed out (PowerShell overhead on Windows)
            # Still consider it available, just with unknown version
            print("   Info: Gemini version detection timed out")
            print("   Using defaults: gemini-3.1-pro-preview")
            return {
                "available": True,
                "model": "gemini-3.1-pro-preview",
                "context_window": 1000000,
                "version": "unknown (timeout)",
            }

        except Exception as e:
            return {"available": False, "error": str(e)}

    def inspect_claude(self) -> dict:
        """
        Detect Claude CLI and model

        Tries to:
        1. Run `claude --version` to check if CLI exists
        2. Parse version string to detect model (Opus, Sonnet, Haiku)

        Returns:
            {
                "available": bool,
                "model": str,           # e.g. "claude-sonnet-4.5"
                "context_window": int,  # tokens
                "version": str,         # CLI version
                "error": str            # if not available
            }
        """
        try:
            # Try claude --version (using platform-aware helper)
            # Increased timeout to 15s for Windows PowerShell overhead
            result = self._run_cli_command(["claude", "--version"], timeout=15)

            if result.returncode != 0:
                return {"available": False, "error": "claude CLI not found or not in PATH"}

            version_output = result.stdout.strip()

            # Parse model from version string
            # Default to claude-sonnet-4.5 (current as of Sept 2025)
            model = "claude-sonnet-4.5"
            context_window = 200000

            output_lower = version_output.lower()

            # Claude Code uses Sonnet 4.5 by default
            if "claude code" in output_lower:
                model = "claude-sonnet-4.5"
                context_window = 200000

            # Detect model from version string
            elif "opus" in output_lower:
                if "4" in version_output:
                    model = "claude-opus-4"
                else:
                    model = "claude-opus-3"
                context_window = 200000

            elif "sonnet" in output_lower:
                if "4.5" in version_output or "4-5" in version_output:
                    model = "claude-sonnet-4.5"
                elif "4" in version_output:
                    model = "claude-sonnet-4"
                else:
                    model = "claude-sonnet-3.5"
                context_window = 200000

            elif "haiku" in output_lower:
                if "4" in version_output:
                    model = "claude-haiku-4"
                else:
                    model = "claude-haiku-3"
                context_window = 200000

            return {"available": True, "model": model, "context_window": context_window, "version": version_output}

        except FileNotFoundError:
            return {"available": False, "error": "claude command not found. Is Anthropic CLI installed?"}

        except subprocess.TimeoutExpired:
            # claude --version timed out (PowerShell overhead on Windows)
            # Still consider it available, just with unknown version
            print("   Info: Claude version detection timed out")
            print("   Using defaults: claude-sonnet-4.5")
            return {
                "available": True,
                "model": "claude-sonnet-4.5",
                "context_window": 200000,
                "version": "unknown (timeout)",
            }

        except Exception as e:
            return {"available": False, "error": str(e)}

    def get_capabilities_summary(self) -> dict:
        """
        Get complete capabilities summary

        Returns:
            {
                "gemini": {...},
                "claude": {...},
                "system_ready": bool
            }
        """
        gemini = self.inspect_gemini()
        claude = self.inspect_claude()

        return {"gemini": gemini, "claude": claude, "system_ready": gemini["available"] and claude["available"]}
