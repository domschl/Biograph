# Packaging and Deploying biograph-sensor-zsh on GNU Guix

GNU Guix does not use systemd. Instead, it uses **GNU Shepherd** as its service manager/init system. For managing user-level daemons like the zsh history sensor, Guix provides **Guix Home** (a declarative configuration system for user environments) or direct configuration of a user-level **GNU Shepherd** instance.

The package and service definition is provided in [biograph.scm](file:///home/dsc/Codeberg/Biograph/packaging/guix/biograph.scm).

---

## 1. Guix Package Definition

The package definition uses `python-build-system` to build the Python package under `sensors/zsh` with the Hatchling backend, propagating its dependencies (`python-watchdog` and `python-httpx`).

### How to Build the Package Locally
You can build the package directly from the root of the Biograph repository using:

```bash
guix build -f packaging/guix/biograph.scm
```

To install the package into your current profile:

```bash
guix package -f packaging/guix/biograph.scm
```

---

## 2. Deploying with Guix Home (Declarative)

If you manage your user environment using **Guix Home** (configured via `home-configuration.scm` and activated using `guix home reconfigure`), you can import and extend the service type defined in [biograph.scm](file:///home/dsc/Codeberg/Biograph/packaging/guix/biograph.scm).

### Example `home-configuration.scm`
Here is how you can use the service in your Guix Home configuration:

```scheme
(use-modules (guix gexp)
             (gnu home)
             (gnu packages)
             ;; Load the biograph module from your load-path or relative file path
             (biograph))

(home-configuration
 (services
  (list
   ;; Declare and configure the zsh sensor service
   (service home-biograph-sensor-zsh-service-type
            (home-biograph-sensor-zsh-configuration
             ;; Optionally override the package (e.g. to use a local build or channel version)
             (package biograph-sensor-zsh)
             ;; Optionally provide a custom config path (defaults to ~/.config/biograph/config.toml)
             (config-file #f)))
   
   ;; Other home services...
   )))
```

To reconfigure your environment:

```bash
guix home reconfigure home-configuration.scm
```

Once reconfigured, the service is managed by Shepherd and starts automatically when you log in.

---

## 3. Deploying with GNU Shepherd (Imperative / User Service)

If you are not using Guix Home (e.g., using Guix on a foreign distribution) but run a user-level GNU Shepherd instance (`shepherd` launched from your `.zprofile` or X session), you can configure the service directly in `~/.config/shepherd/init.scm`.

### Example `~/.config/shepherd/init.scm`
Add the following configuration to define the service:

```scheme
(define biograph-sensor-zsh
  (shepherd-service
   (provision '(biograph-sensor-zsh))
   (documentation "Biograph zsh history sensor daemon")
   (requirement '())
   (start (make-forkexec-constructor
           ;; Points to the executable in your profile
           '("biograph-sensor-zsh")
           #:environment-variables '("PYTHONUNBUFFERED=1")
           ;; Log files can be redirected to a dedicated file
           #:log-file (string-append (getenv "HOME") "/.local/share/biograph/sensor-zsh.log")))
   (stop (make-kill-destructor))
   (respawn? #t)))

;; Register the service with Shepherd
(register-services (list biograph-sensor-zsh))

;; Start it immediately on daemon launch
(start-service biograph-sensor-zsh)
```

---

## 4. Managing the Sensor Service

Once deployed, you can use the standard Shepherd client command `herd` to manage the zsh sensor daemon:

*   **Check status:**
    ```bash
    herd status biograph-sensor-zsh
    ```
*   **Stop the sensor:**
    ```bash
    herd stop biograph-sensor-zsh
    ```
*   **Start the sensor:**
    ```bash
    herd start biograph-sensor-zsh
    ```
*   **View logs:**
    *   If using the Shepherd direct setup, read the file:
        ```bash
        tail -f ~/.local/share/biograph/sensor-zsh.log
        ```
    *   If using Guix Home (without custom log path), standard output goes to the main shepherd log:
        ```bash
        tail -f ~/.local/state/log/shepherd.log
        ```
