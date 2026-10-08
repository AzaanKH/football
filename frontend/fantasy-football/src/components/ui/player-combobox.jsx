
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
          className="w-full justify-between border-yardline bg-turf font-normal text-chalk hover:bg-turf/70 hover:text-chalk"
        >
          {value ? (
            <span className="truncate">
              {value.name} {value.team ? `(${value.team})` : ''}
            </span>
          ) : (
            <span className="text-chalk-muted">{placeholder}</span>
          )}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      {/* Never taller than the space Radix measures below/above the trigger, so the
          list stays reachable when a phone keyboard shrinks the viewport */}
      <PopoverContent
        className="flex max-h-[min(22rem,var(--radix-popover-content-available-height))] w-[min(350px,calc(100vw-2rem))] flex-col border-yardline bg-popover p-0"
        align="start"
      >
        {/* Filtering happens on the server; cmdk only handles keyboard navigation */}
        <Command className="min-h-0 bg-transparent" shouldFilter={false}>
          <CommandInput
            value={query}
            onValueChange={setQuery}
            placeholder="Search by name or team..."
            className="text-chalk placeholder:text-chalk-muted"
          />
          <CommandList className="max-h-none min-h-0">
            {status === "idle" && (
              <CommandEmpty className="py-6 text-center text-sm text-chalk-secondary">
                No player found.
              </CommandEmpty>
            )}
            {status === "loading" && visible.length === 0 && (
              <div className="py-6 text-center text-sm text-chalk-secondary">Searching...</div>
            )}
            {status === "error" && (
              <div role="alert" className="py-6 text-center text-sm text-chalk">
                Search failed. Check that the backend is running.
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
                    className="cursor-pointer text-chalk aria-selected:bg-accent aria-selected:text-chalk"
                  >
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        isSelected ? "opacity-100 text-scrimmage" : "opacity-0"
                      )}
                    />
                    <span className="flex-1 truncate">{player.name}</span>
                    {player.team && (
                      <span className="ml-2 text-xs text-chalk-secondary">{player.team}</span>
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
