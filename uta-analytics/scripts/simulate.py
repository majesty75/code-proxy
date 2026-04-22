#!/usr/bin/env python3
import os
import sys
import time
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Simulate real-time log generation by streaming an existing file.")
    parser.add_argument("input_file", help="Path to the source log file")
    parser.add_argument("--output-dir", default="/uta/UTA_FULL_Logs", help="Directory where the file watcher is listening (default: /uta/UTA_FULL_Logs)")
    parser.add_argument("--delay", type=float, default=0.05, help="Delay in seconds between writing each line (default: 0.05)")
    parser.add_argument("--batch-size", type=int, default=1, help="Number of lines to write at once (default: 1)")
    
    args = parser.parse_args()
    
    input_path = Path(args.input_file)
    if not input_path.exists() or not input_path.is_file():
        print(f"Error: Input file '{input_path}' does not exist.")
        sys.exit(1)
        
    output_dir = Path(args.output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        print(f"Error: Permission denied to create directory '{output_dir}'. You may need to run with sudo or choose a different output directory.")
        sys.exit(1)
        
    output_path = output_dir / input_path.name
    
    print(f"Starting simulation...")
    print(f"Source: {input_path}")
    print(f"Destination: {output_path}")
    print(f"Speed: {args.batch_size} lines every {args.delay} seconds")
    print("Press Ctrl+C to stop.\n")
    
    # Open the file in write mode first to clear any existing content
    # or to create it if it doesn't exist, simulating a fresh log file creation.
    with open(output_path, 'w') as f_out:
        pass
        
    try:
        with open(input_path, 'r') as f_in, open(output_path, 'a') as f_out:
            lines_batch = []
            lines_written = 0
            
            for line in f_in:
                lines_batch.append(line)
                
                if len(lines_batch) >= args.batch_size:
                    for l in lines_batch:
                        f_out.write(l)
                    f_out.flush()
                    lines_written += len(lines_batch)
                    lines_batch = []
                    time.sleep(args.delay)
                    
            # Flush any remaining lines
            if lines_batch:
                for l in lines_batch:
                    f_out.write(l)
                f_out.flush()
                lines_written += len(lines_batch)
                
            print(f"\nSimulation complete. {lines_written} lines written to {output_path}.")
            
    except KeyboardInterrupt:
        print(f"\nSimulation stopped by user. Wrote {lines_written} lines so far.")
        sys.exit(0)

if __name__ == "__main__":
    main()
