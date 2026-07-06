;;; Module:      biograph
;;; Description: GNU Guix package and service definition for the Biograph zsh sensor.
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

(define-public biograph-sensor-zsh
  (package
    (name "biograph-sensor-zsh")
    (version "0.1.0")
    (source (git-reference
             (url "https://codeberg.org/domschl/Biograph.git")
             (commit (string-append "v" version)))) ; Adjust to specific commit/tag if needed
    (build-system python-build-system)
    (arguments
     (list
      #:tests? #f ; Disable tests during package build to avoid test-only dependency errors
      #:phases
      #~(modify-phases %standard-phases
          (add-after 'unpack 'chdir
            (lambda _
              (chdir "sensors/zsh"))))))
    (native-inputs
     (list python-hatchling))
    (propagated-inputs
     (list python-watchdog
           python-httpx))
    (home-page "https://codeberg.org/domschl/Biograph")
    (synopsis "Biograph zsh history sensor")
    (description
     "Watches @file{~/.zsh_history} and sends shell-cmd events to the Biograph backend.")
    (license license:mit)))

;;;
;;; Guix Home Service Definition
;;;

(define-record-type* <home-biograph-sensor-zsh-configuration>
  home-biograph-sensor-zsh-configuration make-home-biograph-sensor-zsh-configuration
  home-biograph-sensor-zsh-configuration?
  (package home-biograph-sensor-zsh-configuration-package
           (default biograph-sensor-zsh))
  (config-file home-biograph-sensor-zsh-configuration-config-file
               (default #f))) ; #f will fall back to ~/.config/biograph/config.toml

(define-public home-biograph-sensor-zsh-service-type
  (service-type
   (name 'home-biograph-sensor-zsh)
   (extensions
    (list (service-extension
           ;; Extend Guix Home's Shepherd service list
           ( @ (gnu home services shepherd) home-shepherd-service-type)
           (lambda (config)
             (let ((pkg (home-biograph-sensor-zsh-configuration-package config))
                   (cfg (home-biograph-sensor-zsh-configuration-config-file config)))
               (list (shepherd-service
                      (provision '(biograph-sensor-zsh))
                      (documentation "Biograph zsh history sensor daemon")
                      (requirement '())
                      (start #~(make-forkexec-constructor
                                (list (string-append #$pkg "/bin/biograph-sensor-zsh"))
                                #:environment-variables
                                (append
                                 '("PYTHONUNBUFFERED=1")
                                 (if #$cfg
                                     (list (string-append "BIOGRAPH_CONFIG=" #$cfg))
                                     '()))))
                      (stop #~(make-kill-destructor))
                      (respawn? #t))))))))
   (default-value (home-biograph-sensor-zsh-configuration))
   (description "Runs the Biograph zsh history sensor as a Shepherd user daemon.")))

;; Evaluate to the package by default so the file can be built with `guix build -f`
biograph-sensor-zsh
