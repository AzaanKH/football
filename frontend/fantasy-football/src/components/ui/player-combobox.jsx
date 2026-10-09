"use client"

import * as React from "react"
import { Check, ChevronsUpDown } from "lucide-react"

import { cn } from "../../lib/utils"
import { isCancel, searchPlayers } from "../../lib/api"
import { Button } from "./button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "./command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "./popover"

const SEARCH_DEBOUNCE_MS = 250

/**
 * Searchable player picker backed by server-side search, so every player is
 * reachable (not just a preloaded page). `value` is a player object
 * ({player_id, name, team}) so the label survives new search results.
 */
export function PlayerCombobox({
  position,
  season,
  week,
  value,
  onValueChange,
  excludeIds = [],
  placeholder = "Select player...",
}) {
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState("")
  const [results, setResults] = React.useState([])
  const [status, setStatus] = React.useState("idle") // idle | loading | error

  React.useEffect(() => {
    if (!open) return undefined

    // Each keystroke cancels the previous search, so results can't arrive out of order
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      setStatus("loading")
      try {
        const players = await searchPlayers(
          { position, season, week, search: query.trim() },
          controller.signal
        )
        setResults(players)
        setStatus("idle")
      } catch (error) {
        if (!isCancel(error)) setStatus("error")
      }
    }, query ? SEARCH_DEBOUNCE_MS : 0)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [open, query, position, season, week])

  const handleOpenChange = (next) => {
    setOpen(next)
    if (!next) setQuery("")
  }

  const visible = results.filter(
    (p) => p.player_id === value?.player_id || !excludeIds.includes(p.player_id)
  )

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label={value ? `Player: ${value.name}` : placeholder}
          className="w-full justify-between bg-slate-700/50 border-slate-600 text-white hover:bg-slate-700 hover:text-white"
        >
          {value ? (
            <span className="truncate">
              {value.name} {value.team ? `(${value.team})` : ''}
            </span>
          ) : (
            <span className="text-slate-400">{placeholder}</span>
          )}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[350px] p-0 bg-slate-800 border-slate-700" align="start">
        {/* Filtering happens on the server; cmdk only handles keyboard navigation */}
        <Command className="bg-transparent" shouldFilter={false}>
          <CommandInput
            value={query}
            onValueChange={setQuery}
            placeholder="Search by name or team..."
            className="text-white placeholder:text-slate-400"
          />
          <CommandList className="max-h-[300px]">
            {status === "idle" && (
              <CommandEmpty className="text-slate-400 py-6 text-center text-sm">
                No player found.
              </CommandEmpty>
            )}
            {status === "loading" && visible.length === 0 && (
              <div className="text-slate-400 py-6 text-center text-sm">Searching...</div>
            )}
            {status === "error" && (
              <div role="alert" className="text-destructive py-6 text-center text-sm">
                Search failed. Is the backend running?
              </div>
            )}
            <CommandGroup>
              {visible.map((player) => {
                const isSelected = player.player_id === value?.player_id

                return (
                  <CommandItem
                    key={player.player_id}
                    value={player.player_id}
                    onSelect={() => {
                      onValueChange(isSelected ? null : player)
                      handleOpenChange(false)
                    }}
                    className="text-white hover:bg-slate-700 aria-selected:bg-slate-700 cursor-pointer"
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        isSelected ? "opacity-100 text-primary" : "opacity-0"
                      )}
                    />
                    <span className="flex-1 truncate">{player.name}</span>
                    {player.team && (
                      <span className="text-slate-400 text-xs ml-2">{player.team}</span>
                    )}
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
