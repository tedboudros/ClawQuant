"""ASCII art banner for ClawQuant CLI."""

BANNER = r"""
   _____ _                 ____                    _            
  / ____| |               / __ \                  | |           
 | |    | | __ _ _      _| |  | |_   _  __ _ _ __ | |_          
 | |    | |/ _` | \ /\ / / |  | | | | |/ _` | '_ \| __|         
 | |____| | (_| |\ V  V /| |__| | |_| | (_| | | | | |_          
  \_____|_|\__,_| \_/\_/  \____\_\__,_|\__,_|_| |_|\__| 
"""

TAGLINE = "Lightweight event-driven trading advisory system"


def print_banner() -> None:
    """Print the banner and tagline."""
    print(BANNER)
    print(f"  {TAGLINE}")
    print()
