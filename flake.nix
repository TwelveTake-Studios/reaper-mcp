{
  description = "Reaper MCP Server development environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in {
      devShells = forAllSystems (system:
        let pkgs = import nixpkgs { inherit system; };
        in {
          default = pkgs.mkShell {
            packages = [
              pkgs.python312
              pkgs.python312Packages.pip
              pkgs.python312Packages.virtualenv
            ];

            shellHook = ''
              # Create a virtual environment if it doesn't exist, then activate it.
              if [ ! -d .venv ]; then
                python -m venv .venv
              fi
              source .venv/bin/activate
            '';
          };
        });
    };
}
