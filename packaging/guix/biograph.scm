;;; Module:      biograph
;;; Description: GNU Guix package and service definition for the Biograph unified shell sensor (bash & zsh).
;;; License:     MIT

(define-module (biograph)
  #:use-module (guix gexp)
  #:use-module (guix records)
  #:use-module (guix packages)
  #:use-module (guix git-download)
  #:use-module (guix build-system python)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (gnu packages python-build)
  #:use-module (gnu packages python-xyz)
  #:use-module (gnu packages python-web))

(define-public biograph-sensor-shell
  (package
    (name "biograph-sensor-shell")
    (version "0.2.3")
    (source (git-reference
             (url "https://github.com/domschl/Biograph.git")
             (commit (string-append "v" version)))) ; Adjust to specific commit/tag if needed
    (build-system python-build-system)
    (arguments
     (list
      #:tests? #f ; Disable tests during package build to avoid test-only dependency errors
      #:phases
      #~(modify-phases %standard-phases
          (add-after 'unpack 'chdir
            (lambda _
              (chdir "sensors/shell"))))))
    (native-inputs
     (list python-hatchling))
    (propagated-inputs
     (list python-watchdog
           python-httpx))
    (home-page "https://github.com/domschl/Biograph")
    (synopsis "Biograph unified shell history sensor (bash & zsh)")
    (description
     "Watches @file{~/.bash_history} and @file{~/.zsh_history} and sends shell-cmd events to the Biograph backend.")
    (license license:mit)))

;; Backward-compatibility alias
(define-public biograph-sensor-zsh biograph-sensor-shell)

;;;
;;; Guix Home Service Definition
;;;

(define-record-type* <home-biograph-sensor-shell-configuration>
  home-biograph-sensor-shell-configuration make-home-biograph-sensor-shell-configuration
  home-biograph-sensor-shell-configuration?
  (package home-biograph-sensor-shell-configuration-package
           (default biograph-sensor-shell))
  (config-file home-biograph-sensor-shell-configuration-config-file
               (default #f))) ; #f will fall back to ~/.config/biograph/config.toml

(define-public home-biograph-sensor-shell-service-type
  (service-type
   (name 'home-biograph-sensor-shell)
   (extensions
    (list (service-extension
           ;; Extend Guix Home's Shepherd service list
           ( @ (gnu home services shepherd) home-shepherd-service-type)
           (lambda (config)
             (let ((pkg (home-biograph-sensor-shell-configuration-package config))
                   (cfg (home-biograph-sensor-shell-configuration-config-file config)))
               (list (shepherd-service
                      (provision '(biograph-sensor-shell biograph-sensor-zsh))
                      (documentation "Biograph unified shell history sensor daemon")
                      (requirement '())
                      (start #~(make-forkexec-constructor
                                (list (string-append #$pkg "/bin/biograph-sensor-shell"))
                                #:environment-variables
                                (append
                                 '("PYTHONUNBUFFERED=1")
                                 (if #$cfg
                                     (list (string-append "BIOGRAPH_CONFIG=" #$cfg))
                                     '()))))
                      (stop #~(make-kill-destructor))
                      (respawn? #t))))))))
   (default-value (home-biograph-sensor-shell-configuration))
   (description "Runs the Biograph unified shell history sensor as a Shepherd user daemon.")))

;; Backward-compatibility alias
(define-public home-biograph-sensor-zsh-service-type home-biograph-sensor-shell-service-type)
(define-public home-biograph-sensor-zsh-configuration home-biograph-sensor-shell-configuration)

;; Evaluate to the package by default so the file can be built with `guix build -f`
biograph-sensor-shell
