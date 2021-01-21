package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"os"
	"path"
	"strings"

	"phenix-apps/tmpl"
	"phenix-apps/util"
	"phenix/types"

	"github.com/mitchellh/mapstructure"
)

type Metadata struct {
	AgentDir string `mapstructure:"agentDir"`
}

type HostMetadata struct {
	Agent         string `mapstructure:"agent"`
	AgentArgs     string `mapstructure:"agentArgs"`
	AutoStart     bool   `mapstructure:"autoStart"`
	CustomService struct {
		InjectPath string `mapstructure:"injectPath"`
		ScriptPath string `mapstructure:"scriptPath"`
	} `mapstructure:"customService"`
	ServiceType string `mapstructure:"serviceType"`
}

var logger *log.Logger

func main() {
	out := os.Stderr

	if env, ok := os.LookupEnv("PHENIX_LOG_FILE"); ok {
		var err error

		out, err = os.OpenFile(env, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		if err != nil {
			log.Fatal("unable to open phenix log file for writing")
		}

		defer out.Close()
	}

	logger = log.New(out, " cc-dropper ", log.Ldate|log.Ltime|log.Lmsgprefix)

	if len(os.Args) != 2 {
		logger.Fatal("incorrect amount of args provided")
	}

	body, err := ioutil.ReadAll(os.Stdin)
	if err != nil {
		logger.Fatal("unable to read JSON from STDIN")
	}

	stage := os.Args[1]

	if stage != "configure" && stage != "pre-start" {
		fmt.Print(string(body))
		return
	}

	exp, err := util.DecodeExperiment(body)
	if err != nil {
		logger.Fatalf("decoding experiment: %v", err)
	}

	switch stage {
	case "configure":
		if err := configure(exp); err != nil {
			logger.Fatalf("failed to execute configure stage: %v", err)
		}
	case "pre-start":
		if err := preStart(exp); err != nil {
			logger.Fatalf("failed to execute pre-start stage: %v", err)
		}
	}

	body, err = json.Marshal(exp)
	if err != nil {
		logger.Fatal("unable to convert experiment to JSON")
	}

	fmt.Print(string(body))
}

func configure(exp *types.Experiment) error {
	startupDir := exp.Spec.BaseDir() + "/startup"

	app := util.ExtractApp(exp.Spec.Scenario(), "cc-dropper")

	if app == nil {
		// TODO: yell loudly
		return nil
	}

	var md Metadata

	if err := mapstructure.Decode(app.Metadata(), &md); err != nil {
		return fmt.Errorf("decoding app metadata: %w", err)
	}

	for _, host := range app.Hosts() {
		var hmd HostMetadata

		if err := mapstructure.Decode(host.Metadata(), &hmd); err != nil {
			// TODO: yell loudly
			continue
		}

		nodes := util.FindNodesByNameRegex(exp, host.Hostname())

		if nodes == nil {
			// TODO: yell loudly
			continue
		}

		for _, node := range nodes {
			agentPath := md.AgentDir + "/" + hmd.Agent

			switch strings.ToUpper(node.Hardware().OSType()) {
			case "WINDOWS":
				var (
					startupFile  = startupDir + "/" + node.General().Hostname() + "-phenix-command-and-control.ps1"
					scheduleFile = startupDir + "/phenix-command-and-control-scheduler.cmd"
				)

				if !strings.HasSuffix(agentPath, ".exe") {
					agentPath = agentPath + ".exe"
				}

				node.AddInject(startupFile, "/minimega/phenix-command-and-control.ps1", "", "")

				if hmd.AutoStart {
					node.AddInject(scheduleFile, "ProgramData/Microsoft/Windows/Start Menu/Programs/StartUp/phenix-command-and-control-scheduler.cmd", "", "")
				}
			default:
				startupFile := startupDir + "/" + node.General().Hostname() + "-phenix-command-and-control.sh"

				switch strings.ToLower(hmd.ServiceType) {
				case "systemd":
					var (
						serviceFile = startupDir + "/" + node.General().Hostname() + "-phenix-command-and-control.service"
						serviceLink = startupDir + "/symlinks/phenix-command-and-control.service"
					)

					node.AddInject(startupFile, "/minimega/phenix-command-and-control.sh", "", "")
					node.AddInject(serviceFile, "/etc/systemd/system/phenix-command-and-control.service", "", "")

					if hmd.AutoStart {
						node.AddInject(serviceLink, "/etc/systemd/system/multi-user.target.wants/phenix-command-and-control.service", "", "")
					}
				case "sysinitv":
					var (
						serviceFile = startupDir + "/phenix-command-and-control"
						serviceLink = startupDir + "/symlinks/S99-phenix-command-and-control"
					)

					node.AddInject(startupFile, "/minimega/phenix-command-and-control.sh", "", "")
					node.AddInject(serviceFile, "/etc/init.d/phenix-command-and-control", "", "")

					if hmd.AutoStart {
						node.AddInject(serviceLink, "/etc/rc5.d/S99-phenix-command-and-control", "", "")
					}
				case "custom":
					node.AddInject(startupFile, hmd.CustomService.InjectPath, "", "")
				}

				node.AddInject(agentPath, "/minimega/"+path.Base(agentPath), "", "")
			}
		}
	}

	return nil
}

func preStart(exp *types.Experiment) error {
	startupDir := exp.Spec.BaseDir() + "/startup"

	app := util.ExtractApp(exp.Spec.Scenario(), "cc-dropper")

	if app == nil {
		// TODO: yell loudly
		return nil
	}

	var md Metadata

	if err := mapstructure.Decode(app.Metadata(), &md); err != nil {
		return fmt.Errorf("decoding app metadata: %w", err)
	}

	for _, host := range app.Hosts() {
		var hmd HostMetadata

		if err := mapstructure.Decode(host.Metadata(), &hmd); err != nil {
			// TODO: yell loudly
			continue
		}

		nodes := util.FindNodesByNameRegex(exp, host.Hostname())

		if nodes == nil {
			// TODO: yell loudly
			continue
		}

		for _, node := range nodes {
			switch strings.ToUpper(node.Hardware().OSType()) {
			case "WINDOWS":
				var (
					startupFile  = startupDir + "/" + node.General().Hostname() + "-phenix-command-and-control.ps1"
					scheduleFile = startupDir + "/phenix-command-and-control-scheduler.cmd"
				)

				if err := tmpl.CreateFileFromTemplate("cc-dropper/windows-startup.tmpl", hmd, startupFile, 0755); err != nil {
					return fmt.Errorf("generating windows command and control startup script: %w", err)
				}

				if hmd.AutoStart {
					if err := tmpl.CreateFileFromTemplate("cc-dropper/windows-scheduler.tmpl", hmd, scheduleFile, 0755); err != nil {
						return fmt.Errorf("generating windows command and control service script: %w", err)
					}
				}
			default:
				startupFile := startupDir + "/" + node.General().Hostname() + "-phenix-command-and-control.sh"

				if err := tmpl.CreateFileFromTemplate("cc-dropper/linux-startup.tmpl", hmd, startupFile, 0755); err != nil {
					return fmt.Errorf("generating linux command and control startup script: %w", err)
				}

				switch strings.ToLower(hmd.ServiceType) {
				case "systemd":
					serviceFile := startupDir + "/" + node.General().Hostname() + "-phenix-command-and-control.service"

					if err := tmpl.CreateFileFromTemplate("cc-dropper/systemd-service.tmpl", hmd, serviceFile, 0644); err != nil {
						return fmt.Errorf("generating linux command and control service file: %w", err)
					}

					if hmd.AutoStart {
						symlinksDir := startupDir + "/symlinks"

						if err := os.MkdirAll(symlinksDir, 0755); err != nil {
							return fmt.Errorf("creating experiment startup symlinks directory path: %w", err)
						}

						if err := os.Symlink("../phenix-command-and-control.service", symlinksDir+"/phenix-command-and-control.service"); err != nil {
							// Ignore the error if it was for the symlinked file already existing.
							if !strings.Contains(err.Error(), "file exists") {
								return fmt.Errorf("generating linux command and control service link: %w", err)
							}
						}
					}
				case "sysinitv":
					serviceFile := startupDir + "/phenix-command-and-control"

					if err := tmpl.CreateFileFromTemplate("cc-dropper/sysinitv-service.tmpl", hmd, serviceFile, 0755); err != nil {
						return fmt.Errorf("generating linux command and control service file: %w", err)
					}

					if hmd.AutoStart {
						symlinksDir := startupDir + "/symlinks"

						if err := os.MkdirAll(symlinksDir, 0755); err != nil {
							return fmt.Errorf("creating experiment startup symlinks directory path: %w", err)
						}

						if err := os.Symlink("../init.d/phenix-command-and-control", symlinksDir+"/S99-phenix-command-and-control"); err != nil {
							// Ignore the error if it was for the symlinked file already existing.
							if !strings.Contains(err.Error(), "file exists") {
								return fmt.Errorf("generating linux command and control service link: %w", err)
							}
						}
					}
				case "custom":
					if hmd.CustomService.ScriptPath != "" {
						if _, err := os.Stat(hmd.CustomService.ScriptPath); err != nil {
							return fmt.Errorf("custom service script not found on disk")
						}

						body, err := ioutil.ReadFile(hmd.CustomService.ScriptPath)
						if err != nil {
							return fmt.Errorf("reading custom service script %s: %w", hmd.CustomService.ScriptPath, err)
						}

						custom := strings.Split(string(body), "\n")
						custom = append(custom, "##### Generated by phenix cc-dropper app ######")

						//Generate the template into a string
						existing := new(bytes.Buffer)

						if err := tmpl.GenerateFromTemplate("cc-dropper/linux-startup.tmpl", hmd, existing); err != nil {
							return fmt.Errorf("generating linux command and control startup script: %w", err)
						}

						//Grab all the startup stuff for CC and add it the the users script
						custom = append(custom, strings.Split(existing.String(), "\n")...)

						err = ioutil.WriteFile(startupFile, []byte(strings.Join(custom, "\n")), 0755)
						if err != nil {
							return fmt.Errorf("writing %s: %w", startupFile, err)
						}
					}
				}
			}
		}
	}

	return nil
}
