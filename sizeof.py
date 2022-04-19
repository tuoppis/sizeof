#!/bin/python3
from os import path, scandir
from math import log10
from fnmatch import fnmatch
from argparse import ArgumentParser
from datetime import datetime, timedelta

PREFIX = (" ", "K", "M", "G", "T", "P")
PREFIX_B = ("  ", "Ki", "Mi", "Gi", "Ti", "Pi")

def round_significant(num, significant_digits):
    if not num: return 0
    rfact = significant_digits - int(log10(abs(num))) - 1
    num = round(num, rfact)
    return num if rfact > 0 else int(num)

def format_size(size, scale=1000, digits=3):
    prefix = PREFIX if scale != 1024 else PREFIX_B
    for S in prefix:
        if size < scale: return (f"{round_significant(size, digits)}{S}").rjust(digits + 2 + len(S))
        size /= scale
    return f"{round_significant(size, digits)}E{'i' if scale == 1024 else ''}".rjust(digits + 3)
    
def format_date(fdate, now, full_date = False):
    if fdate == None: return ""
    date = datetime.fromtimestamp(fdate)
    if full_date: return date.isoformat()
    
    year = date.year if date.year != now.year else ""
    month = f"{date.month:02}" if year or date.month != now.month else ""
    day = f"{date.day:02}" if month or date.day != now.day else ""
    date_str = f"{year}-{month}-{day}" if year or month or day else ""
    
    hour = f"{date.hour:02}" if date_str or date.hour != now.hour else ""
    minute = f"{date.minute:02}" if hour or date.minute != now.minute else ""
    second = f"{date.second:02}" if minute or date.second != now.second else ""    
    time_str = f"{hour}:{minute}:{second}" if second else ""
    
    return date_str + ("T" if date_str and time_str else "") + time_str
    
def to_int_size(size_str):
    length = range(1, len(PREFIX))
    number = ""
    scale = 0
    is_binary = False
    for ch in size_str:
        if scale > 0: # after scale unit is set, only accept 'i' for binary scale.
            is_binary = ch == "i"
            break
        if ch == " " or ch == "_": continue #ignore white spaces or underscore (for thousands separator)
        if "0" <= ch <= "9" or ch == ".": number += ch
        else:
            ch = ch.upper()
            for idx in length:
                if ch == PREFIX[idx]: 
                    scale = idx
                    break
            else:
                raise ValueError(f"Unknown symbol {ch} in {size_str}")
   
    return float(number) * (1024 if is_binary else 1000) ** scale

def to_int_date(date_str, now):
    try:
        return datetime.fromisoformat(date_str).timestamp()
    except ValueError as verr:
        pass
    
    units = {"y": 0, "year": 0, "M": 0, "month": 0, "w": 0, "week": 0, "d": 0, "day": 0,
            "h": 0, "hour": 0, "m": 0, "min": 0, "minute": 0,  "": 0, "sec": 0, "second": 0}
    cur_int_str = ""
    cur_unit_str = ""
    is_unit = False
    
    def cut_num():
        nonlocal is_unit, cur_int_str, cur_unit_str
        if is_unit:
            unit = cur_unit_str[0:-1] if cur_unit_str.endswith("s") else cur_unit_str
            if not unit in units: raise ValueError("Time unit not recognized! " + unit)
            units[unit] += int(cur_int_str or 1)
            cur_int_str = ""
            cur_unit_str = ""
            is_unit = False
    
    for ch in date_str:
        if ch == " " or ch == "_": cut_num()
        elif "0" <= ch <= "9":
            cut_num()
            cur_int_str += ch
        else:
            is_unit = True
            cur_unit_str += ch

    if is_unit: cut_num()
    elif cur_int_str: units["sec"] += int(cur_int_str)
    
    delta = timedelta(
        days = units["d"] + units["day"] + 7*(units["w"] + units["week"]), 
        hours = units["h"] + units["hour"],
        minutes = units["m"] + units["min"] + units["minute"],
        seconds = units[""] + units["sec"] + units["second"]
    )
    month = units["M"] + units["month"]
    years = units["y"] + units["year"] + month // 12
    month = now.month - month % 12
    
    if month <= 0:
        years += 1
        month += 12

    return (now.replace(year = now.year - years, month = month) - delta).timestamp()

def and_match(fname, patterns, on_empty = True):
    if not patterns: return on_empty
    for p in patterns:
        if not fnmatch(fname, p): return False
    return True

def or_match(fname, patterns, on_empty = True):
    if not patterns: return on_empty
    for p in patterns:
        if fnmatch(fname, p): return True
    return False

def matches(fname, args):
    if args.insensitive: fname = fname.lower()
    return or_match(fname, args.or_any) and and_match(fname, args.and_all) and\
        not or_match(fname, args.not_any, False) and not and_match(fname, args.not_all, False)
        
def int_match_pair(min_limit, max_limit, value):
    if min_limit == None: return value <= max_limit if max_limit != None else True
    if max_limit == None: return value >= min_limit
    return (min_limit <= value <= max_limit) if min_limit <= max_limit else not (max_limit < value < min_limit)

def stat_match(stat, args):
    return int_match_pair(args.min_bytes, args.max_bytes, stat.st_size) and\
            int_match_pair(args.min_date, args.max_date, stat.st_mtime)

def process_directory(loc, args):
    with scandir(loc) as it:
        matched_size = 0
        matched_in_subdirs = 0
        matched_count = 0
        total_files = 0
        total_size = 0
        for entry in it:
            if entry.is_symlink():
                if not args.follow_links: continue
            if entry.is_dir():
                msize, mcount, tsize, tcount = process_directory(entry.path, args)
                matched_in_subdirs += msize
                matched_count += mcount
                total_size += tsize
                total_files += tcount
            elif entry.is_file():
                stat = entry.stat()
                fsize = stat.st_size
                total_files += 1
                total_size += fsize
                if matches(entry.name, args) and stat_match(stat, args):
                    if args.files: print(format_size(fsize, args.scale), entry.path)
                    matched_size += fsize
                    matched_count += 1

    if args.directories: print(format_size(matched_size, args.scale), loc)
    return matched_size + matched_in_subdirs, matched_count, total_size, total_files

def process_args():
    parser = ArgumentParser(
        description="Find total size of files of given patterns in the specified folder and subfolders.",
        epilog="Boolean ops (and, or, etc.) form groups that operate separately and are joined with an 'and' operation.\n"
            "Eg. 'sizeof a b -a d -a e -o c -n w -n x --not-all y z' is evaluated as:\n"
            "(a or b or c) and (d and e) and not (w or x) and not (y and z), where a..z are patterns.\n"
            "Notice that unmarked patterns are added to the 'or' group except after the --not-all tag, which are "
            "added to the 'not-all' group. There is currently no way to form custom groupings. Also notice that 'sizeof X -a Y' "
            "works as intended because how the groups are joined. More general way is 'sizeof -a X -a Y'.")
    parser.add_argument("patterns", metavar="P", nargs="*", default=[], help="if the first P is an existing folder, it's same as -p P, otherwise P's are equivalent to -o P")
    parser.add_argument("-d", "--directories", action="store_true", help="prints total matched size in each folder.")
    parser.add_argument("-f", "--files", action="store_true", help="prints the matched files.")
    parser.add_argument("-v", "--verbose", action="store_true", help="same as -dfs.")
    parser.add_argument("-s", "--summary", action="store_true", help="prints summary of the search.")
    parser.add_argument("-q", "--quiet", action="store_true", help="outputs only the total matched size.")
    parser.add_argument("-p", "--path", help="starting location, default is the current dir.")
    parser.add_argument("-b", "--binary", dest="scale", action="store_const", default=1000, const=1024, help="use binary instead of si units.")
    parser.add_argument("--follow-links", action="store_true", help="follow links pointing outside the path.")
    parser.add_argument("-i", "--insensitive", action="store_true", help="case insensitive matching.")
#logical ops
    parser.add_argument("-a", "--and", dest="and_all", metavar="P", action="append", help=" (P1 & ... & Pn), select if all are matched.")
    parser.add_argument("-o", "--or", dest="or_any", metavar="P", action="append", default=[], help=" (P1 | ... | Pn), select if any are matched.")
    parser.add_argument("-n", "--not", dest="not_any", metavar="P",  action="append", help="~(P1 | ... | Pn), reject if any are matched.")
    parser.add_argument("--not-all", dest="not_all", metavar="P", nargs="+", action="append", help="~(P1 & ... & Pn), reject if all are matched.")
#comp ops
    parser.add_argument("-m", "--min-size", metavar="S", help="minimum size with K, M, etc. ")
    parser.add_argument("-M", "--max-size", metavar="S", help="maximum size with K, M, etc.")
    parser.add_argument("-t", "--newer", metavar="AGE", help="a minimum date (YYYY-MM-DD) or maximum age (#y#M#w#d#h#m#s).")
    parser.add_argument("-T", "--older", metavar="AGE", help="reverse of --newer.")

    args = parser.parse_args()
    args.now = datetime.now()

    try:
        args.min_date = to_int_date(args.newer, args.now) if args.newer else None
        args.max_date = to_int_date(args.older, args.now) if args.older else None
    except ValueError as verr:
        ArgumentParser.exit(1, f"Error parsing time argument: {verr}\n"
            "Use either ISO stardard date (YYYY-MM-DD or YYYY-MM-DDThh:mm:ss) or duration such as '1week_5min'.\n"
            "Durations can have 'y', 'year', 'M', 'month', 'w', 'week', 'h', 'hour', 'm', 'min', 'minute', 's', 'sec', 'second', or their plurals."
            " If only a bare number is given it is considered to be a 'second'. Omitted number is assumed to be 1.\n"
            "Eg. '-t minute' is equal to '-t 1min' and '-t 60'.")
    try:
        args.min_bytes = to_int_size(args.min_size) if args.min_size else None
        args.max_bytes = to_int_size(args.max_size) if args.max_size else None
    except ValueError as verr:
        ArgumentParser.exit(1, f"Error parsing a size argument: {verr}\n"
            "Use a number followed by an optional size prefix, 'K', 'M', 'G', 'T', 'P', (factor 1000), or +'i' for the corresponding binary units (factor 1024). "
            "For convinience lower cases are also accepted.")

    if not args.path:
        args.path = args.patterns.pop(0) if args.patterns and path.isdir(args.patterns[0]) else "."
    
    args.or_any.extend(args.patterns)
    args.not_all = args.not_all[0] if args.not_all else None
    if args.quiet:
        if args.verbose or args.files or args.directories or args.summary:
            parser.error("Cannot not use -v, -s, -d, or -f with -q")
    if args.verbose:
        args.files = True
        args.summary = True
    if args.insensitive:
        args.or_any = [x.lower() for x in (args.or_any or [])]
        args.not_any = [x.lower() for x in (args.not_any or [])]
        args.and_all = [x.lower() for x in (args.and_all or [])]
        args.not_all = [x.lower() for x in (args.not_all or [])]
    return args

def paren_array(array, join_str, pre_str = ""):
    if not array: return ""
    array = [x for x in array if x]
    if len(array) == 1: return f"{pre_str}{array[0]}" if array[0] else ""
    return f"{pre_str}({join_str.join(array)})" if array else ""

def int_limits_str(min_limit, max_limit, name, format_func):
    if min_limit == None: return f"{name} ≤ {format_func(max_limit)}" if max_limit != None else ""
    if max_limit == None: return f"{name} ≥ {format_func(min_limit)}"
    
    min_str = format_func(min_limit)
    max_str = format_func(max_limit)
    
    return f"{min_str} ≤ {name} ≤ {max_str}" if min_limit <= max_limit else f"not {max_str} < {name} < {min_str}"
    
def print_patterns(args):
    res = paren_array(
        [paren_array(args.or_any, " or "), paren_array(args.and_all, " and "),
        paren_array(args.not_any, " or ", "not "), paren_array(args.not_all, " and ", "not ")],
        " and ") or "*"
    size_lim = int_limits_str(args.min_bytes, args.max_bytes, "SIZE", lambda x: format_size(x, args.scale).strip())
    date_lim = int_limits_str(args.min_date, args.max_date, "DATE", lambda x: format_date(x, args.now))
    res += f", {size_lim}" if size_lim else ""
    res += f", {date_lim}" if date_lim else ""
    return res

def main():
    args = process_args()
    if not args.quiet: print(f"IN {args.path} NAME {print_patterns(args)}")
    m_size, m_count, t_size, t_count = process_directory(args.path, args)
    if args.quiet:
        print(m_size)
        return
        
    t_size_str = format_size(t_size, args.scale).strip()
    t_count_str = str(t_count) # TODO: localized formatting
    m_size_str = format_size(m_size, args.scale).strip()
    m_count_str = str(m_count) # TODO: localized formatting

    if args.summary:
        if m_count:
            print(f"Matched {m_size_str} / {t_size_str} bytes in {m_count_str} / {t_count_str} files.")
        else:
            print(f"No matches in {t_count_str} files.")
    else:
        print(f"{m_size_str}")

if __name__=="__main__": main()
