{
  description = "Reaper MCP Server Environment";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }: {
    devShells.x86_64-linux.default = let
      pkgs = import nixpkgs { system = "x86_64-linux"; };
    in pkgs.mkShell {
      packages = [
        pkgs.python312
        # Add any other python dependencies you need here, like:
        pkgs.python312Packages.pip
        pkgs.python311Packages.virtualenv
      ];

      shellHook = ''
        # 1. Create a virtual environment if it doesn't exist
        if [ ! -d .venv ]; then
          python -m venv .venv
        fi
        
        # 2. Activate it
        source .venv/bin/activate
      '';
    };
  };
}