package main

import (
	"log"

	"example.com/sample-001/services/internal/launch"
)

func main() {
	if err := launch.Worker("reconciliation"); err != nil {
		log.Fatal(err)
	}
}
