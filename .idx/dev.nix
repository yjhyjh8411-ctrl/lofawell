# To learn more about how to use Nix to configure your environment
# see: https://developers.google.com/idx/guides/customize-idx-env
{ pkgs, ... }: {
  # Which nixpkgs channel to use.
  channel = "stable-23.11"; # or "unstable"
  # Use https://search.nixos.org/packages to find packages
  packages = [
    pkgs.python3
    pkgs.python3Packages.pip
    pkgs.pipx
    pkgs.nodePackages.pm2
    pkgs.stdenv.cc.cc.lib
  ];
  # Sets environment variables in the workspace
  env = {
    LD_LIBRARY_PATH = "${pkgs.stdenv.cc.cc.lib}/lib";
  };
  idx = {
    # Search for the extensions you want on https://open-vsx.org/ and use "publisher.id"
    extensions = [
      # "vscodevim.vim"
      "google.gemini-cli-vscode-ide-companion"
    ];
    # Enable previews and customize configuration
    previews = {
      enable = true;
      previews = [{
        # Unique ID for this preview
        id = "web";
        # Display name for this preview
        displayName = "Web Server";
        # Command to run to start the server. This command first installs dependencies and then runs the app.
        command = [
          "bash"
          ,
          "-c",
          "cd functions && python3 -m pip install -r requirements.txt && python3 app.py"
        ];
        # Environment variables to set for this command
        env = {
          # Make the server available on all network interfaces
          "HOST" = "0.0.0.0";
        };
        # What to do when the command exits
        onExit = "restart";
      }];
    };
    # Workspace lifecycle hooks
    workspace = {
      # Runs when a workspace is first created
      onCreate = {
        # Open editors for the following files by default, if they exist:
        default.openFiles = [ "lofawell/app.py", "lofawell/requirements.txt" ];
      };
      # Runs when the workspace is (re)started
      onStart = {
      };
    };
  };
}