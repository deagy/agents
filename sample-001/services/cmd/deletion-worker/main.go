package main

import (
	"log"

	"example.com/sample-001/services/internal/launch"
)

func main() {
	if err := launch.Worker("deletion"); err != nil {
		log.Fatal(err)
	}
}
