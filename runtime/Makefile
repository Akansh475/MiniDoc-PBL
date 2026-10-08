# MiniDocker Runtime Layer Makefile
CC ?= gcc
CFLAGS ?= -Wall -Wextra -O2 -std=c99
TARGET = process_manager
SRC = process_manager.c

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(SRC) process_manager.h
	$(CC) $(CFLAGS) $(SRC) -o $(TARGET)

clean:
	rm -f $(TARGET) *.o
