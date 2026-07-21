package main

import (
	"log"

	"example.com/sample-001/services/internal/launch"
)

func main() {
	if err := launch.Worker("promotion"); err != nil {
		log.Fatal(err)
	}
}
